"""Tests de app/services/rag.py (indice vectorial Qdrant).

Qdrant se sustituye por un cliente falso que registra llamadas: lo que se
prueba es la logica del servicio (pool, overrides de settings, fallback de
embeddings, creacion idempotente de coleccion/indices, filtros de tenant,
contrato de ingest/search), no el propio falso.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.rag as rag
from app.models.entities import Base, Company, Document, DocumentChunk


class _FakeCollections:
    def __init__(self, names):
        self.collections = [type("C", (), {"name": n}) for n in names]


class _FakeCollectionInfo:
    def __init__(self, payload_schema=None):
        self.payload_schema = payload_schema or {}


class _FakeQdrantClient:
    def __init__(self, collections=(), payload_schema=None, exists=True):
        self._names = list(collections)
        self._info = _FakeCollectionInfo(payload_schema)
        self._exists = exists
        self.created_collections = []
        self.created_indexes = []
        self.upserts = []
        self.deletes = []
        self.queries = []

    def get_collections(self):
        return _FakeCollections(self._names)

    def create_collection(self, collection_name, **kwargs):
        self.created_collections.append((collection_name, kwargs))
        self._names.append(collection_name)

    def get_collection(self, collection_name):
        return self._info

    def create_payload_index(self, collection_name, field_name, field_schema, wait=True):
        self.created_indexes.append(field_name)

    def collection_exists(self, collection_name):
        return self._exists

    def upsert(self, collection_name, points):
        self.upserts.append((collection_name, points))

    def delete(self, collection_name, points_selector, wait=True):
        self.deletes.append((collection_name, points_selector))

    def query_points(self, **kwargs):
        self.queries.append(kwargs)
        return type("QR", (), {"points": []})()


def _index(monkeypatch, **settings_overrides):
    settings = type("S", (), {"qdrant_url": "http://qdrant:6333", **settings_overrides})()
    monkeypatch.setattr(rag, "get_settings", lambda: settings)
    return rag.RAGIndex()


def test_redact_secrets_compone_core_y_llm():
    text = "url con password=secreto123 y Authorization: Bearer token-abc"
    out = rag.redact_secrets(text)
    assert "secreto123" not in out
    assert "token-abc" not in out


def test_qdrant_client_pool_reutiliza_y_limpia(monkeypatch):
    rag.clear_qdrant_pool()  # arranque limpio: el pool es global de proceso
    try:
        made = []
        monkeypatch.setattr(rag, "QdrantClient", lambda url: made.append(url) or object())
        a = rag.get_qdrant_client("http://a:1")
        assert rag.get_qdrant_client("http://a:1") is a
        b = rag.get_qdrant_client("http://b:2")
        assert b is not a
        assert made == ["http://a:1", "http://b:2"]
        rag.clear_qdrant_pool()
        assert rag.get_qdrant_client("http://a:1") is not a
    finally:
        rag.clear_qdrant_pool()  # no dejar clientes falsos para la suite posterior


def test_collection_dims_y_hybrid_respetan_settings(monkeypatch):
    idx = _index(monkeypatch)
    assert idx._collection() == "portfolio_research_documents"
    assert idx._dims() == 384
    assert idx._hybrid_wanted(None) is False
    assert idx._hybrid_wanted(True) is True
    assert idx._hybrid_wanted(False) is False

    idx2 = _index(monkeypatch, rag_collection="custom", rag_dense_dims=512, rag_hybrid_enabled=True)
    assert idx2._collection() == "custom"
    assert idx2._dims() == 512
    assert idx2._hybrid_wanted(None) is True


def test_dense_vectors_cae_a_sentence_transformers_si_fastembed_falla(monkeypatch):
    idx = _index(monkeypatch)

    def boom(texts, model):
        raise RuntimeError("onnx roto con password=clave99")

    import app.services.hybrid_retrieval as hr
    monkeypatch.setattr(hr, "embed_dense", boom)

    class _Arr(list):
        def tolist(self):
            return list(self)

    class _ST:
        def encode(self, texts, normalize_embeddings=True):
            assert normalize_embeddings is True
            return _Arr([[0.1] * 384 for _ in texts])

    monkeypatch.setattr(rag.RAGIndex, "_embedder", lambda self: _ST())
    out = idx._dense_vectors(["hola"])
    assert out == [[0.1] * 384]


def test_sparse_embeddings_none_si_fastembed_no_esta(monkeypatch):
    idx = _index(monkeypatch, rag_hybrid_enabled=True)
    import app.services.hybrid_retrieval as hr

    def boom(texts, model):
        raise hr.FastembedUnavailable("sin fastembed")

    monkeypatch.setattr(hr, "embed_sparse", boom)
    assert idx._sparse_embeddings(["x"]) is None


def test_ensure_collection_crea_coleccion_e_indices_si_falta(monkeypatch):
    idx = _index(monkeypatch)
    client = _FakeQdrantClient(collections=[])
    idx._ensure_collection(client)
    assert client.created_collections[0][0] == "portfolio_research_documents"
    assert client.created_indexes == ["tenant_id", "ticker", "entity_type"]


def test_ensure_payload_indexes_solo_crea_los_que_faltan(monkeypatch):
    idx = _index(monkeypatch)
    client = _FakeQdrantClient(
        collections=["portfolio_research_documents"],
        payload_schema={"tenant_id": object()},
    )
    idx._ensure_payload_indexes(client, "portfolio_research_documents")
    assert client.created_indexes == ["ticker", "entity_type"]


def test_query_filter_siempre_incluye_tenant(monkeypatch):
    idx = _index(monkeypatch)
    f = idx._query_filter("AAPL", 7, entity_type="document_chunk")
    assert f is not None
    conds = {c.key: c.match.value for c in f.must}
    assert conds == {"ticker": "AAPL", "tenant_id": 7, "entity_type": "document_chunk"}
    f2 = idx._query_filter(None, 7)
    assert [c.key for c in f2.must] == ["tenant_id"]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _document(db: Session, with_chunks: bool = True) -> Document:
    company = Company(
        ticker="RAG", name="RAG Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    doc = Document(
        company_id=company.id, tenant_id=1, title="10-K 2024", source_type="sec_filing",
    )
    db.add(doc)
    db.flush()
    if with_chunks:
        for i, text in enumerate(["primera parte", "segunda parte"]):
            db.add(DocumentChunk(document_id=doc.id, tenant_id=1, chunk_index=i, text=text, token_count=2))
    db.commit()
    return doc


def test_ingest_document_exige_contexto_tenant(db):
    doc = _document(db)
    db.info.pop("tenant_id")
    with pytest.raises(ValueError, match="Tenant context"):
        rag.RAGIndex().ingest_document(db, doc)


def test_ingest_document_sin_chunks_no_toca_qdrant(db, monkeypatch):
    _index(monkeypatch)
    doc = _document(db, with_chunks=False)
    client = _FakeQdrantClient()
    monkeypatch.setattr(rag.RAGIndex, "client", lambda self: client)
    out = rag.RAGIndex().ingest_document(db, doc)
    assert out == {"chunks_indexed": 0, "collection": "portfolio_research_documents"}
    assert client.upserts == []


def test_ingest_document_dims_mismatch_reporta_error(db, monkeypatch):
    _index(monkeypatch, rag_dense_dims=384)
    doc = _document(db)
    monkeypatch.setattr(rag.RAGIndex, "_dense_vectors", lambda self, texts: [[0.1] * 128 for _ in texts])
    monkeypatch.setattr(rag.RAGIndex, "client", lambda self: _FakeQdrantClient())
    out = rag.RAGIndex().ingest_document(db, doc)
    assert out["chunks_indexed"] == 0
    assert "dims mismatch" in out["error"]


def test_ingest_document_happy_path_indexa_chunks_con_payload(db, monkeypatch):
    _index(monkeypatch)
    doc = _document(db)
    client = _FakeQdrantClient(collections=["portfolio_research_documents"])
    monkeypatch.setattr(rag.RAGIndex, "client", lambda self: client)
    monkeypatch.setattr(rag.RAGIndex, "_dense_vectors", lambda self, texts: [[0.1] * 384 for _ in texts])
    out = rag.RAGIndex().ingest_document(db, doc)
    assert out == {"chunks_indexed": 2, "collection": "portfolio_research_documents"}
    assert len(client.upserts) == 1
    _, points = client.upserts[0]
    assert [p.payload["chunk_index"] for p in points] == [0, 1]
    assert all(p.payload["tenant_id"] == 1 for p in points)
    assert all(p.payload["entity_type"] == "document_chunk" for p in points)
    assert all(p.payload["ticker"] == "RAG" for p in points)
    chunks = db.query(DocumentChunk).order_by(DocumentChunk.chunk_index).all()
    assert all(c.qdrant_point_id for c in chunks)


def test_ingest_document_error_qdrant_se_redacta(db, monkeypatch):
    _index(monkeypatch)
    doc = _document(db)
    client = _FakeQdrantClient(collections=["portfolio_research_documents"])

    def boom(collection_name, points):
        raise RuntimeError("qdrant caido con password=ultrasecreto")

    client.upsert = boom
    monkeypatch.setattr(rag.RAGIndex, "client", lambda self: client)
    monkeypatch.setattr(rag.RAGIndex, "_dense_vectors", lambda self, texts: [[0.1] * 384 for _ in texts])
    out = rag.RAGIndex().ingest_document(db, doc)
    assert out["chunks_indexed"] == 0
    assert "ultrasecreto" not in out["error"]


def test_delete_points_sin_coleccion_no_crea_nada(monkeypatch):
    idx = _index(monkeypatch)
    client = _FakeQdrantClient(exists=False)
    monkeypatch.setattr(rag.RAGIndex, "client", lambda self: client)
    assert idx.delete_tenant_points(1) == 0
    assert client.deletes == []


def test_delete_document_points_filtra_por_tenant_y_documento(monkeypatch):
    idx = _index(monkeypatch)
    client = _FakeQdrantClient(exists=True)
    monkeypatch.setattr(rag.RAGIndex, "client", lambda self: client)
    assert idx.delete_document_points(7, 42) == 1
    _, selector = client.deletes[0]
    conds = {c.key: c.match.value for c in selector.filter.must}
    assert conds == {"tenant_id": 7, "document_id": 42}


def test_search_sin_tenant_devuelve_vacio(monkeypatch):
    idx = _index(monkeypatch)
    assert idx.search("ingresos") == []


def test_search_denso_mapea_contrato_estable(monkeypatch):
    idx = _index(monkeypatch)
    client = _FakeQdrantClient(collections=["portfolio_research_documents"])
    point = type(
        "P", (), {
            "id": "p1",
            "score": 0.87,
            "payload": {
                "text": "ingresos 2024", "ticker": "RAG", "document_id": 5,
                "knowledge_document_id": None, "collection_id": None, "page_number": 3,
                "source_type": "sec_filing", "title": "10-K", "entity_type": "document_chunk",
                "entity_id": 9, "chunk_index": 0,
            },
        }
    )()
    captured = {}
    def _query(**kwargs):
        captured.update(kwargs)
        return type("QR", (), {"points": [point]})()
    client.query_points = _query
    monkeypatch.setattr(rag.RAGIndex, "client", lambda self: client)
    monkeypatch.setattr(rag.RAGIndex, "_dense_vectors", lambda self, texts: [[0.1] * 384])
    rows = idx.search("ingresos", ticker="RAG", tenant_id=1)
    assert len(rows) == 1
    row = rows[0]
    assert row["text"] == "ingresos 2024"
    assert row["score"] == 0.87
    assert row["point_id"] == "p1"
    assert "scores" not in row  # el path denso historico no lo lleva
    # la busqueda filtra siempre por tenant y por el ticker pedido
    conds = {c.key: c.match.value for c in captured["query_filter"].must}
    assert conds == {"ticker": "RAG", "tenant_id": 1}


def test_search_error_devuelve_vacio_sin_leak(monkeypatch):
    idx = _index(monkeypatch)
    monkeypatch.setattr(rag.RAGIndex, "_dense_vectors", lambda self, texts: (_ for _ in ()).throw(RuntimeError("Bearer tok-secreto")))
    assert idx.search("x", tenant_id=1) == []
