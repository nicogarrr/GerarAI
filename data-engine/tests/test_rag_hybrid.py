"""Contrato RAG denso (intacto) + hibrido (aditivo). Todo hermetico.

- NUNCA descarga modelos: ``_dense_vectors``/``_sparse_embeddings`` se
  mockean, y la ausencia de fastembed se simula via ``sys.modules``.
- El cliente Qdrant es un fake en memoria (sin servidor).
"""

from __future__ import annotations

import inspect
import logging
import sys
import types
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Document, DocumentChunk, Tenant
from app.services import hybrid_retrieval as hr
from app.services.rag import RAGIndex

LEGACY_KEYS = {
    "text", "ticker", "document_id", "knowledge_document_id", "collection_id",
    "page_number", "source_type", "title", "score", "point_id", "entity_type",
    "entity_id", "chunk_index",
}


def _payload(**overrides):
    base = {
        "text": "texto",
        "ticker": "SRCH",
        "document_id": 1,
        "knowledge_document_id": None,
        "collection_id": None,
        "page_number": None,
        "source_type": "sec_filing",
        "title": "Titulo",
        "entity_type": "document_chunk",
        "entity_id": 10,
        "chunk_index": 0,
        "tenant_id": 99,
    }
    base.update(overrides)
    return base


def _hit(point_id, score, **payload_overrides):
    return SimpleNamespace(id=point_id, score=score, payload=_payload(**payload_overrides))


class FakeQdrant:
    """Fake minimo: denso (lista) y sparse (NamedSparseVector) distinguibles."""

    def __init__(self, dense_hits=(), sparse_hits=(), fail_sparse=False):
        self.dense_hits = list(dense_hits)
        self.sparse_hits = list(sparse_hits)
        self.fail_sparse = fail_sparse
        self.searches: list[dict] = []
        self.upserted: list = []
        self.created: list = []

    def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name="portfolio_research_documents")])

    def get_collection(self, name):
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(sparse_vectors={"bm25": object()})))

    def create_collection(self, *args, **kwargs):
        self.created.append((args, kwargs))
        return True

    def update_collection(self, *args, **kwargs):
        return True

    def query_points(self, **kwargs):
        from qdrant_client.models import SparseVector

        self.searches.append(kwargs)
        if isinstance(kwargs.get("query"), SparseVector):
            if self.fail_sparse:
                raise RuntimeError("sparse index missing")
            return SimpleNamespace(points=list(self.sparse_hits))
        return SimpleNamespace(points=list(self.dense_hits))

    def upsert(self, **kwargs):
        self.upserted.append(kwargs)
        return True


@pytest.fixture()
def index(monkeypatch):
    idx = RAGIndex()
    monkeypatch.setattr(idx.settings, "rag_hybrid_enabled", False)
    monkeypatch.setattr(idx.settings, "rag_embedding_backend", "fastembed")
    return idx


def _wire(index, monkeypatch, fake):
    monkeypatch.setattr(index, "client", lambda: fake)
    monkeypatch.setattr(index, "_ensure_collection", lambda client: None)


# -- contrato denso intacto ---------------------------------------------------


def test_search_signature_only_adds_optional_hybrid():
    params = inspect.signature(RAGIndex.search).parameters
    assert list(params)[:6] == ["self", "query", "ticker", "limit", "tenant_id", "hybrid"]
    # Unico anadido posterior: filtro opcional por tipo, solo por keyword.
    assert list(params)[6:] == ["entity_type"]
    assert params["entity_type"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["entity_type"].default is None
    assert params["hybrid"].default is None
    assert params["query"].default is inspect.Parameter.empty
    assert params["ticker"].default is None
    assert params["limit"].default == 5
    assert params["tenant_id"].default is None


def test_search_dense_default_returns_legacy_shape_without_scores(index, monkeypatch):
    fake = FakeQdrant(dense_hits=[_hit("p1", 0.91), _hit("p2", 0.42)])
    _wire(index, monkeypatch, fake)
    monkeypatch.setattr(index, "_dense_vectors", lambda texts: [[0.1] * 384 for _ in texts])
    rows = index.search("margen operativo", ticker="SRCH", limit=5, tenant_id=99)
    assert len(rows) == 2
    assert set(rows[0].keys()) == LEGACY_KEYS
    assert "scores" not in rows[0]
    assert rows[0]["score"] == 0.91 and rows[0]["point_id"] == "p1"
    assert len(fake.searches) == 1
    call = fake.searches[0]
    assert call["limit"] == 5
    assert isinstance(call["query"], list) and len(call["query"]) == 384
    must = {c.key: c.match.value for c in call["query_filter"].must}
    assert must == {"ticker": "SRCH", "tenant_id": 99}


def test_search_dense_forced_when_global_hybrid_on(index, monkeypatch):
    monkeypatch.setattr(index.settings, "rag_hybrid_enabled", True)
    fake = FakeQdrant(dense_hits=[_hit("p1", 0.5)])
    _wire(index, monkeypatch, fake)
    monkeypatch.setattr(index, "_dense_vectors", lambda texts: [[0.1] * 384])
    rows = index.search("q", tenant_id=1, hybrid=False)
    assert len(rows) == 1 and "scores" not in rows[0]
    assert len(fake.searches) == 1  # solo denso: sin rama sparse


# -- hibrido ------------------------------------------------------------------


def _hybrid_hits():
    dense = [_hit("A", 0.9), _hit("B", 0.8), _hit("C", 0.1)]
    sparse = [_hit("B", 0.7), _hit("D", 0.6), _hit("A", 0.05)]
    return dense, sparse


def test_search_hybrid_fuses_with_rrf_and_scores(index, monkeypatch):
    monkeypatch.setattr(index.settings, "rag_hybrid_enabled", True)
    dense, sparse = _hybrid_hits()
    fake = FakeQdrant(dense_hits=dense, sparse_hits=sparse)
    _wire(index, monkeypatch, fake)
    monkeypatch.setattr(index, "_dense_vectors", lambda texts: [[0.2] * 384])
    monkeypatch.setattr(
        index, "_sparse_embeddings", lambda texts: [hr.SparseEmbedding([1], [0.5])]
    )
    rows = index.search("capital allocation", limit=4, tenant_id=99)
    assert [r["point_id"] for r in rows] == ["B", "A", "D", "C"]
    assert set(rows[0].keys()) == LEGACY_KEYS | {"scores"}
    assert rows[0]["scores"] == {
        "dense": 0.8,
        "sparse": 0.7,
        "rrf": pytest.approx(1 / 62 + 1 / 61),
    }
    assert rows[0]["score"] == pytest.approx(rows[0]["scores"]["rrf"])
    solo_sparse = next(r for r in rows if r["point_id"] == "D")
    assert solo_sparse["scores"]["dense"] is None
    assert len(fake.searches) == 2  # una densa + una sparse


def test_search_hybrid_weights_are_configurable(index, monkeypatch):
    monkeypatch.setattr(index.settings, "rag_hybrid_enabled", True)
    dense = [_hit("X", 0.9), _hit("Y", 0.1)]
    sparse = [_hit("Y", 0.9), _hit("X", 0.1)]
    fake = FakeQdrant(dense_hits=dense, sparse_hits=sparse)
    _wire(index, monkeypatch, fake)
    monkeypatch.setattr(index, "_dense_vectors", lambda texts: [[0.2] * 384])
    monkeypatch.setattr(
        index, "_sparse_embeddings", lambda texts: [hr.SparseEmbedding([1], [0.5])]
    )
    monkeypatch.setattr(index.settings, "rag_dense_weight", 5.0)
    monkeypatch.setattr(index.settings, "rag_sparse_weight", 1.0)
    assert [r["point_id"] for r in index.search("q", tenant_id=1)] == ["X", "Y"]
    monkeypatch.setattr(index.settings, "rag_dense_weight", 1.0)
    monkeypatch.setattr(index.settings, "rag_sparse_weight", 5.0)
    assert [r["point_id"] for r in index.search("q", tenant_id=1)] == ["Y", "X"]


def test_search_hybrid_sparse_failure_degrades_to_dense(index, monkeypatch, caplog):
    monkeypatch.setattr(index.settings, "rag_hybrid_enabled", True)
    fake = FakeQdrant(dense_hits=[_hit("A", 0.77)], fail_sparse=True)
    _wire(index, monkeypatch, fake)
    monkeypatch.setattr(index, "_dense_vectors", lambda texts: [[0.2] * 384])
    monkeypatch.setattr(
        index, "_sparse_embeddings", lambda texts: [hr.SparseEmbedding([1], [0.5])]
    )
    with caplog.at_level(logging.WARNING, logger="app.services.rag"):
        rows = index.search("q", tenant_id=1)
    assert [r["point_id"] for r in rows] == ["A"]
    assert rows[0]["score"] == 0.77
    assert any("dense-only" in r.getMessage() for r in caplog.records)


def test_search_scopes_both_branches_by_tenant(index, monkeypatch):
    monkeypatch.setattr(index.settings, "rag_hybrid_enabled", True)
    fake = FakeQdrant(dense_hits=[_hit("A", 0.5)], sparse_hits=[_hit("A", 0.4)])
    _wire(index, monkeypatch, fake)
    monkeypatch.setattr(index, "_dense_vectors", lambda texts: [[0.2] * 384])
    monkeypatch.setattr(
        index, "_sparse_embeddings", lambda texts: [hr.SparseEmbedding([1], [0.5])]
    )
    index.search("q", ticker="SRCH", tenant_id=123)
    assert len(fake.searches) == 2
    for call in fake.searches:
        must = {c.key: c.match.value for c in call["query_filter"].must}
        assert must["tenant_id"] == 123
        assert must["ticker"] == "SRCH"


def test_query_change_changes_result_catches_input_blind_mocks(index, monkeypatch):
    """El test tonto: un mock que ignora la query no pasa este test."""

    class QueryEcho(FakeQdrant):
        def query_points(self, **kwargs):
            from qdrant_client.models import SparseVector

            self.searches.append(kwargs)
            qv = kwargs.get("query")
            first = qv[0] if isinstance(qv, list) else 0.0
            if isinstance(qv, SparseVector):
                return SimpleNamespace(points=[_hit("S", 0.4)])
            if first > 5:
                return SimpleNamespace(points=[_hit("LONG", 0.9), _hit("SHORT", 0.1)])
            return SimpleNamespace(points=[_hit("SHORT", 0.9), _hit("LONG", 0.1)])

    monkeypatch.setattr(index.settings, "rag_hybrid_enabled", False)
    fake = QueryEcho()
    _wire(index, monkeypatch, fake)

    def fake_dense(texts):
        return [[float(len(t))] + [0.0] * 383 for t in texts]

    monkeypatch.setattr(index, "_dense_vectors", fake_dense)
    long_rows = index.search("una query deliberadamente larga", tenant_id=1)
    short_rows = index.search("corta", tenant_id=1)
    assert long_rows[0]["point_id"] == "LONG"
    assert short_rows[0]["point_id"] == "SHORT"
    assert long_rows != short_rows


# -- fallback sin dependencia -------------------------------------------------


def test_search_falls_back_to_sentence_transformers_without_fastembed(index, monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "fastembed", None)

    class FakeST:
        def encode(self, texts, normalize_embeddings=True):
            assert normalize_embeddings
            return types.SimpleNamespace(tolist=lambda: [[0.3] * 384 for _ in texts])

    fake = FakeQdrant(dense_hits=[_hit("p1", 0.66)])
    _wire(index, monkeypatch, fake)
    monkeypatch.setattr(index, "_embedder", lambda: FakeST())
    with caplog.at_level(logging.WARNING, logger="app.services.rag"):
        rows = index.search("margen", tenant_id=1)
    assert [r["point_id"] for r in rows] == ["p1"]
    assert any("fastembed" in r.getMessage().lower() for r in caplog.records)


def test_search_never_500s_when_all_backends_down(index, monkeypatch, caplog):
    monkeypatch.setattr(index, "_dense_vectors", lambda texts: (_ for _ in ()).throw(RuntimeError("boom")))
    fake = FakeQdrant()
    _wire(index, monkeypatch, fake)
    with caplog.at_level(logging.WARNING, logger="app.services.rag"):
        assert index.search("q", tenant_id=1) == []
    assert any("RuntimeError" in r.getMessage() for r in caplog.records)


# -- ingesta -------------------------------------------------------------------


def _db_with_document():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="rag-hybrid-t", name="RAG hybrid")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    company = Company(
        ticker="HYBR",
        name="Hybrid Co",
        exchange="TEST",
        currency="USD",
        sector="Technology",
        industry="Software",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    document = Document(
        tenant_id=tenant.id,
        company_id=company.id,
        title="Nota hibrida",
        source_type="test",
    )
    db.add(document)
    db.flush()
    for i, text in enumerate(("margen operativo solido", "operating margin strength")):
        db.add(
            DocumentChunk(
                tenant_id=tenant.id,
                document_id=document.id,
                chunk_index=i,
                text=text,
            )
        )
    db.commit()
    return db, document


def test_ingest_dense_only_keeps_legacy_list_vectors(index, monkeypatch):
    db, document = _db_with_document()
    fake = FakeQdrant()
    _wire(index, monkeypatch, fake)
    monkeypatch.setattr(index, "_dense_vectors", lambda texts: [[0.1] * 384 for _ in texts])
    try:
        result = index.ingest_document(db, document)
    finally:
        db.close()
    assert result == {"chunks_indexed": 2, "collection": "portfolio_research_documents"}
    assert len(fake.upserted) == 1
    for point in fake.upserted[0]["points"]:
        assert isinstance(point.vector, list) and len(point.vector) == 384


def test_ingest_hybrid_writes_named_sparse_vectors(index, monkeypatch):
    monkeypatch.setattr(index.settings, "rag_hybrid_enabled", True)
    db, document = _db_with_document()
    fake = FakeQdrant()
    _wire(index, monkeypatch, fake)
    monkeypatch.setattr(index, "_dense_vectors", lambda texts: [[0.1] * 384 for _ in texts])
    monkeypatch.setattr(
        index,
        "_sparse_embeddings",
        lambda texts: [hr.SparseEmbedding([i + 1], [0.5]) for i, _ in enumerate(texts)],
    )
    try:
        result = index.ingest_document(db, document)
    finally:
        db.close()
    assert result["chunks_indexed"] == 2
    assert "sparse_skipped" not in result
    for point in fake.upserted[0]["points"]:
        assert isinstance(point.vector, dict)
        assert len(point.vector[""]) == 384
        assert list(point.vector["bm25"].indices) != []


def test_ingest_dims_mismatch_fails_loud_without_upsert(index, monkeypatch):
    db, document = _db_with_document()
    fake = FakeQdrant()
    _wire(index, monkeypatch, fake)
    monkeypatch.setattr(index, "_dense_vectors", lambda texts: [[0.1] * 3 for _ in texts])
    try:
        result = index.ingest_document(db, document)
    finally:
        db.close()
    assert result["chunks_indexed"] == 0
    assert "mismatch" in result["error"]
    assert fake.upserted == []


def test_status_reports_backend_additively(index, monkeypatch):
    fake = FakeQdrant()
    _wire(index, monkeypatch, fake)
    status = index.status()
    assert status["configured"] is True
    assert status["collections"] == ["portfolio_research_documents"]
    assert status["embedding_backend"] == "fastembed"
    assert status["hybrid_enabled"] is False


class _IndexClient:
    def __init__(self, schema, exists=True, fail=False):
        self.schema = schema
        self.exists = exists
        self.fail = fail
        self.created = []
        self.indexes = []

    def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name="portfolio_research_documents")] if self.exists else [])

    def create_collection(self, *args, **kwargs):
        self.created.append(args)

    def get_collection(self, name):
        if self.fail:
            raise RuntimeError("down")
        return SimpleNamespace(payload_schema={k: object() for k in self.schema})

    def create_payload_index(self, collection, field_name, field_schema, wait=True):
        self.indexes.append((field_name, str(getattr(field_schema, "value", field_schema))))


def test_payload_indexes_created_only_for_missing_fields():
    from app.services.rag import RAGIndex

    client = _IndexClient(schema=["ticker"])
    RAGIndex()._ensure_collection(client)
    assert sorted(client.indexes) == [("entity_type", "keyword"), ("tenant_id", "integer")]
    again = _IndexClient(schema=["ticker", "tenant_id", "entity_type"])
    RAGIndex()._ensure_collection(again)
    assert again.indexes == []


def test_payload_indexes_created_for_a_new_collection_and_failure_does_not_break():
    from app.services.rag import RAGIndex

    fresh = _IndexClient(schema=[], exists=False)
    RAGIndex()._ensure_collection(fresh)
    assert fresh.created and len(fresh.indexes) == 3
    RAGIndex()._ensure_collection(_IndexClient(schema=[], fail=True))  # no raise
