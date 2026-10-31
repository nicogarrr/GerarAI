"""Tests de app/services/rag.py: ingesta de conocimiento, rebuild_tenant, status y busqueda hibrida.

Mismo enfoque que test_rag_service.py: cliente Qdrant falso que registra
llamadas; lo que se prueba es la logica del servicio.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.rag as rag
import app.services.hybrid_retrieval as hr
from app.models.entities import (
    Base,
    Company,
    Document,
    DocumentChunk,
    KnowledgeDocument,
    KnowledgeChunk,
)


class _FakeCollections:
    def __init__(self, names):
        self.collections = [type("C", (), {"name": n}) for n in names]


class _FakeQdrantClient:
    def __init__(self, collections=("portfolio_research_documents",), exists=True):
        self._names = list(collections)
        self._exists = exists
        self._info = type("I", (), {"payload_schema": {"tenant_id": 1, "ticker": 1, "entity_type": 1}})()
        self.upserts = []
        self.deletes = []
        self.queries = []

    def get_collections(self):
        return _FakeCollections(self._names)

    def create_collection(self, collection_name, **kwargs):
        self._names.append(collection_name)

    def get_collection(self, collection_name):
        return self._info

    def create_payload_index(self, *a, **k):
        return None

    def collection_exists(self, collection_name):
        return self._exists

    def upsert(self, collection_name, points):
        self.upserts.append((collection_name, points))

    def delete(self, collection_name, points_selector, wait=True):
        self.deletes.append((collection_name, points_selector))

    def query_points(self, **kwargs):
        self.queries.append(kwargs)
        return type("QR", (), {"points": []})()


def _index(monkeypatch, **settings):
    s = type("S", (), {"qdrant_url": "http://qdrant:6333", **settings})()
    monkeypatch.setattr(rag, "get_settings", lambda: s)
    return rag.RAGIndex()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _knowledge_doc(db: Session, with_chunks: bool = True) -> KnowledgeDocument:
    doc = KnowledgeDocument(tenant_id=1, title="Carta 2024", document_type="fund_letter")
    db.add(doc)
    db.flush()
    if with_chunks:
        for i, text in enumerate(["primera idea", "segunda idea"]):
            db.add(KnowledgeChunk(
                tenant_id=1, knowledge_document_id=doc.id, chunk_index=i,
                content=text, page_number=i + 1, token_count=2,
            ))
    db.commit()
    return doc


def test_ingest_knowledge_exige_tenant(db):
    doc = _knowledge_doc(db)
    db.info.pop("tenant_id")
    with pytest.raises(ValueError, match="Tenant context"):
        rag.RAGIndex().ingest_knowledge_document(db, doc)


def test_ingest_knowledge_sin_chunks(db, monkeypatch):
    _index(monkeypatch)
    doc = _knowledge_doc(db, with_chunks=False)
    client = _FakeQdrantClient()
    monkeypatch.setattr(rag.RAGIndex, "client", lambda self: client)
    out = rag.RAGIndex().ingest_knowledge_document(db, doc)
    assert out == {"chunks_indexed": 0, "collection": "portfolio_research_documents"}
    assert client.upserts == []


def test_ingest_knowledge_happy_path_payload(db, monkeypatch):
    _index(monkeypatch)
    doc = _knowledge_doc(db)
    client = _FakeQdrantClient()
    monkeypatch.setattr(rag.RAGIndex, "client", lambda self: client)
    monkeypatch.setattr(rag.RAGIndex, "_dense_vectors", lambda self, texts: [[0.1] * 384 for _ in texts])
    out = rag.RAGIndex().ingest_knowledge_document(db, doc)
    assert out == {"chunks_indexed": 2, "collection": "portfolio_research_documents"}
    _, points = client.upserts[0]
    assert [p.payload["chunk_index"] for p in points] == [0, 1]
    assert all(p.payload["tenant_id"] == 1 for p in points)
    assert all(p.payload["entity_type"] == "knowledge_chunk" for p in points)
    assert all(p.payload["knowledge_document_id"] == doc.id for p in points)
    assert points[0].payload["page_number"] == 1
    chunks = db.query(KnowledgeChunk).order_by(KnowledgeChunk.chunk_index).all()
    assert all(c.qdrant_point_id for c in chunks)


def test_ingest_knowledge_dims_mismatch(db, monkeypatch):
    _index(monkeypatch)
    doc = _knowledge_doc(db)
    monkeypatch.setattr(rag.RAGIndex, "_dense_vectors", lambda self, texts: [[0.1] * 10 for _ in texts])
    monkeypatch.setattr(rag.RAGIndex, "client", lambda self: _FakeQdrantClient())
    out = rag.RAGIndex().ingest_knowledge_document(db, doc)
    assert out["chunks_indexed"] == 0
    assert "dims mismatch" in out["error"]


def test_rebuild_tenant_borra_y_reindexa(db, monkeypatch):
    _index(monkeypatch)
    _knowledge_doc(db)
    company = Company(
        ticker="RB", name="RB Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    doc = Document(company_id=company.id, tenant_id=1, title="10-K", source_type="sec_filing")
    db.add(doc)
    db.flush()
    db.add(DocumentChunk(document_id=doc.id, tenant_id=1, chunk_index=0, text="texto", token_count=1))
    db.commit()
    client = _FakeQdrantClient()
    monkeypatch.setattr(rag.RAGIndex, "client", lambda self: client)
    monkeypatch.setattr(rag.RAGIndex, "_dense_vectors", lambda self, texts: [[0.1] * 384 for _ in texts])
    out = rag.RAGIndex().rebuild_tenant(db)
    assert out["tenant_id"] == 1
    assert out["documents"] == 1
    assert out["knowledge_documents"] == 1
    assert out["chunks_indexed"] == 3
    assert out["errors"] == []
    # primero borra los puntos del tenant, despues reindexa
    _, selector = client.deletes[0]
    conds = {c.key: c.match.value for c in selector.filter.must}
    assert conds == {"tenant_id": 1}


def test_rebuild_tenant_exige_tenant(db):
    db.info.pop("tenant_id")
    with pytest.raises(ValueError, match="Tenant context"):
        rag.RAGIndex().rebuild_tenant(db)


def test_status_ok_y_error(monkeypatch):
    idx = _index(monkeypatch)
    client = _FakeQdrantClient()
    monkeypatch.setattr(rag.RAGIndex, "client", lambda self: client)
    out = idx.status()
    assert out["configured"] is True
    assert out["collection"] == "portfolio_research_documents"
    assert "portfolio_research_documents" in out["collections"]

    def boom():
        raise RuntimeError("qdrant caido password=secreto99")

    monkeypatch.setattr(rag.RAGIndex, "client", lambda self: (_ for _ in ()).throw(RuntimeError("qdrant caido password=secreto99")))
    out2 = idx.status()
    assert out2["configured"] is False
    assert "secreto99" not in out2["error"]


def test_hybrid_search_fusiona_rrf_y_degrada_a_denso(monkeypatch):
    idx = _index(monkeypatch, rag_hybrid_enabled=True)
    dense_point = type("P", (), {"id": "d1", "score": 0.9, "payload": {"text": "denso"}})()
    sparse_point = type("P", (), {"id": "s1", "score": 0.8, "payload": {"text": "sparse"}})()
    client = _FakeQdrantClient()
    client.query_points = lambda **k: type("QR", (), {"points": [dense_point]})()
    monkeypatch.setattr(rag.RAGIndex, "_sparse_embeddings", lambda self, texts: [{"indices": [1], "values": [0.5]}])
    monkeypatch.setattr(hr, "to_qdrant_sparse", lambda v: v)
    monkeypatch.setattr(hr, "sparse_search_points", lambda *a, **k: [sparse_point])
    rows = idx._hybrid_search(client, "q", [0.1] * 384, None, 5)
    assert len(rows) == 2
    assert all("scores" in r for r in rows)
    assert {r["text"] for r in rows} == {"denso", "sparse"}

    # si el sparse falla, devuelve solo denso sin campo scores
    def boom(*a, **k):
        raise RuntimeError("sparse roto")

    monkeypatch.setattr(hr, "sparse_search_points", boom)
    rows2 = idx._hybrid_search(client, "q", [0.1] * 384, None, 5)
    assert len(rows2) == 1
    assert rows2[0]["text"] == "denso"
    assert "scores" not in rows2[0]
