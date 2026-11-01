"""El denso del conocimiento es PROPIO (v2c del piloto): no toca el vector chat legacy.

Regresion cubierta: hasta este cambio el knowledge RAG reusaba
rag_dense_model/rag_dense_dims (MiniLM 384, los del portfolio_research legacy).
Subir a e5-large por esa via habria reindexado el chat legacy en 1024 dims
contra una coleccion creada a 384.
"""

from __future__ import annotations

from datetime import date

from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.services.knowledge_rag import runtime
from app.services.knowledge_rag.chunking import ChunkConfig
from app.services.knowledge_rag.domain import Block, DocType, ExtractedDocument, Section, SourceMetadata
from app.services.knowledge_rag.ingest import register_source
from app.services.knowledge_rag.jobs import run_ingest_job
from app.services.knowledge_rag.store import KnowledgeStore
from tests.knowledge_rag_helpers import FakeEmbedder, fake_count

CFG = ChunkConfig(child_max_tokens=50, child_overlap_tokens=8, parent_max_tokens=160)


def _meta() -> SourceMetadata:
    return SourceMetadata("Carta", "https://e.org/c.pdf", "es", DocType.LETTER, "public_domain", "A", date(1990, 1, 1))


def _doc(text: str) -> ExtractedDocument:
    return ExtractedDocument([Section(("C",), [Block(text, page=1)])], "fake")


def test_dense_defaults_son_v2c_y_el_legacy_no_cambia() -> None:
    s = Settings(_env_file=None)
    assert s.knowledge_rag_dense_model == "intfloat/multilingual-e5-large"
    assert s.knowledge_rag_dense_dims == 1024
    # El legacy (vector chat de portfolio_research_documents) sigue en MiniLM 384.
    assert s.rag_dense_model == "sentence-transformers/all-MiniLM-L6-v2"
    assert s.rag_dense_dims == 384


def test_dense_override_por_entorno(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_RAG_DENSE_MODEL", "org/modelo-x")
    monkeypatch.setenv("KNOWLEDGE_RAG_DENSE_DIMS", "768")
    s = Settings(_env_file=None)
    assert s.knowledge_rag_dense_model == "org/modelo-x"
    assert s.knowledge_rag_dense_dims == 768


def test_make_embedder_usa_el_modelo_del_conocimiento(monkeypatch) -> None:
    seen: dict[str, str] = {}

    class Spy:
        def __init__(self, dense: str, sparse: str, dims: int = 0) -> None:
            seen["dense"] = dense
            seen["sparse"] = sparse

    monkeypatch.setattr(runtime, "LocalEmbedder", Spy)
    runtime.make_embedder(
        Settings(_env_file=None, rag_dense_model="legacy", knowledge_rag_dense_model="conocimiento")
    )
    assert seen["dense"] == "conocimiento"


def test_make_store_usa_las_dims_del_conocimiento(monkeypatch) -> None:
    seen: dict[str, int] = {}

    class SpyStore:
        def __init__(self, client, collection: str, dims: int) -> None:
            seen["dims"] = dims

    monkeypatch.setattr(runtime, "KnowledgeStore", SpyStore)
    import qdrant_client

    monkeypatch.setattr(qdrant_client, "QdrantClient", lambda *a, **k: object())
    runtime.make_store(
        Settings(_env_file=None, qdrant_url="http://qdrant:6333", rag_dense_dims=384,
                 knowledge_rag_dense_dims=1024)
    )
    assert seen["dims"] == 1024


def test_el_job_cuenta_tokens_con_el_modelo_del_conocimiento(tmp_path, monkeypatch) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'd.sqlite'}")
    Base.metadata.create_all(engine)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    text = "El margen de seguridad protege contra el error. La volatilidad no es riesgo."
    (inbox / "c.txt").write_text(text)
    settings = Settings(
        _env_file=None, knowledge_rag_enabled=True, knowledge_rag_inbox_dir=inbox,
        knowledge_rag_min_free_gb=0.0,
    )
    store = KnowledgeStore(QdrantClient(":memory:"), "kd")
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        sid = register_source(db, path=inbox / "c.txt", relative_path="c.txt", meta=_meta(), tenant_id=1).source.id
        called: list[str] = []
        monkeypatch.setattr(runtime, "make_counter", lambda model: called.append(model) or fake_count)
        out = run_ingest_job(
            db, sid, settings, store=store, embedder=FakeEmbedder(),
            extractor=lambda _p: _doc(text), config=CFG,
        )
        assert out["status"] == "ok"
        assert called == [settings.knowledge_rag_dense_model]


def test_e5_prefija_docs_y_consulta_y_minilm_no(monkeypatch) -> None:
    from app.services.knowledge_rag import embedding

    sent: list[list[str]] = []
    monkeypatch.setattr(embedding, "embed_dense", lambda texts, model, batch_size=None: sent.append(list(texts)) or [[0.0]])
    e5 = embedding.LocalEmbedder("intfloat/multilingual-e5-large", dims=1024)
    e5.dense_docs(["hola", "cartera"])
    e5.dense_query("que hora es")
    assert sent[0] == ["passage: hola", "passage: cartera"]
    assert sent[1] == ["query: que hora es"]
    # MiniLM (legacy y default historico): sin prefijos, byte a byte.
    mini = embedding.LocalEmbedder("sentence-transformers/all-MiniLM-L6-v2", dims=384)
    sent.clear()
    mini.dense_docs(["hola"])
    mini.dense_query("que hora es")
    assert sent[0] == ["hola"]
    assert sent[1] == ["que hora es"]


def test_dims_del_embedder_son_las_del_setting(monkeypatch) -> None:
    from app.services.knowledge_rag import runtime as rt

    seen: dict[str, int] = {}

    class Spy:
        def __init__(self, dense: str, sparse: str, dims: int = 0) -> None:
            seen["dims"] = dims

    monkeypatch.setattr(rt, "LocalEmbedder", Spy)
    rt.make_embedder(Settings(_env_file=None, knowledge_rag_dense_dims=1024))
    assert seen["dims"] == 1024


def test_default_de_coleccion_va_con_el_modelo() -> None:
    s = Settings(_env_file=None)
    assert s.knowledge_rag_collection == "knowledge_rag_v2"


def test_coleccion_existente_con_otras_dims_error_claro() -> None:
    import pytest

    from app.services.knowledge_rag.store import CollectionConfigError

    client = QdrantClient(":memory:")
    KnowledgeStore(client, "vieja", dims=384).ensure_collection()
    with pytest.raises(CollectionConfigError, match="384"):
        KnowledgeStore(client, "vieja", dims=1024).ensure_collection()
    # Mismas dims: trabaja sin error ni recrear.
    KnowledgeStore(client, "vieja", dims=384).ensure_collection()


def test_retrieval_usa_dense_query_e_ingesta_dense_docs(tmp_path) -> None:
    from app.services.knowledge_rag.ingest import index_source, parent_resolver, register_source
    from app.services.knowledge_rag.retrieval import search_knowledge

    class Spy(FakeEmbedder):
        def __init__(self) -> None:
            self.calls: list[str] = []

        def dense_docs(self, texts):
            self.calls.append("docs")
            return super().dense_docs(texts)

        def dense_query(self, text):
            self.calls.append("query")
            return super().dense_query(text)

    engine = create_engine(f"sqlite:///{tmp_path / 's.sqlite'}")
    Base.metadata.create_all(engine)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    text = "El margen de seguridad protege contra el error. La volatilidad no es riesgo."
    (inbox / "c.txt").write_text(text)
    store = KnowledgeStore(QdrantClient(":memory:"), "kc")
    spy = Spy()
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        sid = register_source(db, path=inbox / "c.txt", relative_path="c.txt", meta=_meta(), tenant_id=1).source.id
        index_source(db, sid, path=inbox / "c.txt", store=store, embedder=spy,
                     extractor=lambda _p: _doc(text), counter=fake_count, config=CFG)
        res = search_knowledge("margen de seguridad", tenant_id=1, store=store, embedder=spy,
                               resolve_parents=parent_resolver(db))
        assert res.citations
    assert spy.calls[0] == "docs"
    assert "query" in spy.calls
