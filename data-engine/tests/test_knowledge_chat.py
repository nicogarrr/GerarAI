"""Doctrina: aislamiento, texto literal y degradación sin inventar páginas."""
import asyncio
import json
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument
from app.models.entities import Base
from app.services.knowledge_chat import ask_library, retrieve


def setup_library():
    db = Session(create_engine("sqlite://"))
    Base.metadata.create_all(db.get_bind())
    for tenant, author, kind, text, page in [
        (1, "Buffett", "fund_letter", "We buy wonderful businesses. Repurchases can add value at sensible prices.", 8),
        (2, "Buffett", "fund_letter", "Repurchases SECRET for tenant two", 9),
        (1, "Magallanes", "fund_letter", "Repurchases depend on the price and capital needs.", None),
        (1, "Other", "book", "Repurchases appear in this book too.", 1),
    ]:
        doc = KnowledgeDocument(tenant_id=tenant, title=author, author=author,
                                document_type=kind, status="ready")
        db.add(doc)
        db.flush()
        db.add(KnowledgeChunk(tenant_id=tenant, knowledge_document_id=doc.id,
                              chunk_index=0, content=text, page_number=page))
    db.commit()
    db.info["tenant_id"] = 1
    return db


class Provider:
    def __init__(self, payload=None, fail=False):
        self.payload = payload
        self.fail = fail
        self.request = None

    async def complete(self, request):
        self.request = request
        if self.fail:
            raise RuntimeError("unavailable")
        sources = json.loads(request.messages[1].content)["sources"]
        payload = self.payload if self.payload is not None else {"answers": [
            {"text": "Las recompras se valoran según el precio.", "chunk_id": sources[0]["chunk_id"],
             "quote": "Repurchases can add value at sensible prices."}
        ]}
        return SimpleNamespace(text=json.dumps(payload), degraded=False)


def test_letters_exact_author_and_tenant_scope(monkeypatch):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    db = setup_library()
    rows, mode = retrieve(db, "repurchases", scope="letters", author="Buffett")
    assert len(rows) == 1 and rows[0][0].page_number == 8
    assert mode == "solo_texto"
    rows, _ = retrieve(db, "repurchases", scope="library")
    assert len(rows) == 3


def test_verified_citation_comes_from_database(monkeypatch):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    db = setup_library()
    provider = Provider()
    result = asyncio.run(ask_library(db, "repurchases", author="Buffett", provider=provider))
    assert result["status"] == "ok" and result["kind"] == "doctrina"
    citation = result["answers"][0]["citation"]
    assert citation["page_number"] == 8 and citation["author"] == "Buffett"
    assert citation["publication_date"] is None
    assert provider.request.model == "space-bunny-free"


def test_fabricated_quote_and_new_numbers_are_not_shown(monkeypatch):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    db = setup_library()
    chunk = retrieve(db, "repurchases", scope="letters", author="Buffett")[0][0][0]
    for item in [
        {"chunk_id": chunk.id, "quote": "Fabricated quote about repurchases", "text": "fake"},
        {"chunk_id": chunk.id, "quote": "Repurchases can add value at sensible prices.", "text": "Rentabilidad del 50%"},
        {"chunk_id": 99999, "quote": "Repurchases can add value at sensible prices.", "text": "fake"},
    ]:
        result = asyncio.run(ask_library(db, "repurchases", author="Buffett", provider=Provider({"answers": [item]})))
        assert result["status"] == "fragmentos"
        assert all(a["text"] is None for a in result["answers"])


def test_failing_provider_preserves_exact_sources_and_unknown_page(monkeypatch):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    result = asyncio.run(ask_library(setup_library(), "repurchases", author="Magallanes", provider=Provider(fail=True)))
    assert result["status"] == "fragmentos"
    assert result["answers"][0]["citation"]["page_number"] is None


def test_unknown_question_and_missing_tenant_are_honest(monkeypatch):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    db = setup_library()
    provider = Provider()
    result = asyncio.run(ask_library(db, "satellites launch", provider=provider))
    assert result["status"] == "sin_datos" and provider.request is None
    db.info.clear()
    assert retrieve(db, "repurchases", scope="library")[0] == []


def test_semantic_payload_rehydrated_and_foreign_chunk_refused(monkeypatch):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "1")
    db = setup_library()
    from app.services.rag import RAGIndex
    monkeypatch.setattr(RAGIndex, "search", lambda *args, **kwargs: [
        {"entity_id": 2, "text": "spoofed"}, {"entity_id": 1, "text": "spoofed"},
    ])
    rows, mode = retrieve(db, "¿Cómo asignar capital?", scope="letters", author="Buffett")
    assert mode == "semantica_y_texto" and len(rows) == 1
    assert rows[0][0].content.startswith("We buy wonderful")


def test_paid_configuration_never_calls_provider(monkeypatch):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    import app.services.knowledge_chat as chat
    settings = chat.get_settings().model_copy(update={"opencode_go_model": "paid-model"})
    monkeypatch.setattr(chat, "get_settings", lambda: settings)
    monkeypatch.setattr(chat, "create_chat_llm_provider", lambda *args: (_ for _ in ()).throw(AssertionError("paid")))
    result = asyncio.run(ask_library(setup_library(), "repurchases"))
    assert result["status"] == "fragmentos"


def test_multi_page_chunk_never_attributes_quote_to_first_page(monkeypatch):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    db = setup_library()
    chunk = db.get(KnowledgeChunk, 1)
    chunk.metadata_ = {"block_metadata": [{"page": 8}, {"page": 9}]}
    db.commit()
    result = asyncio.run(ask_library(db, "repurchases", author="Buffett", provider=Provider()))
    assert result["answers"][0]["citation"]["page_number"] is None


def test_no_pool_checkout_during_vector_or_llm_after_tenant_lookup(monkeypatch):
    from sqlalchemy import select
    from sqlalchemy.pool import QueuePool

    from app.models import Tenant
    from app.services.rag import RAGIndex

    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "1")
    engine = create_engine("sqlite://", poolclass=QueuePool, pool_size=1, max_overflow=0)
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="pool-test", name="pool")
    db.add(tenant)
    db.flush()
    tenant_id = tenant.id
    document = KnowledgeDocument(tenant_id=tenant_id, title="Letter", author="Buffett",
                                 document_type="fund_letter", status="ready")
    db.add(document)
    db.flush()
    chunk = KnowledgeChunk(tenant_id=tenant_id, knowledge_document_id=document.id,
                           chunk_index=0, content="Repurchases can add value at sensible prices.")
    db.add(chunk)
    db.flush()
    chunk_id = chunk.id
    db.commit()
    # Reproduce get_db: lookup del tenant más lectura lexical previa.
    assert db.scalar(select(Tenant).where(Tenant.external_id == "pool-test")).id == tenant_id
    db.info["tenant_id"] = tenant_id
    assert db.scalar(select(KnowledgeChunk).where(KnowledgeChunk.id == chunk_id)) is not None
    assert engine.pool.checkedout() == 1
    phases = []

    def search(*args, **kwargs):
        assert engine.pool.checkedout() == 0
        assert db.info["tenant_id"] == tenant_id
        phases.append("vector")
        return [{"entity_id": chunk_id}]

    class PoolProvider(Provider):
        async def complete(self, request):
            assert engine.pool.checkedout() == 0
            assert db.info["tenant_id"] == tenant_id
            phases.append("llm")
            return await super().complete(request)

    monkeypatch.setattr(RAGIndex, "search", search)
    result = asyncio.run(ask_library(db, "repurchases", author="Buffett", provider=PoolProvider()))
    assert result["status"] == "ok"
    assert phases == ["vector", "llm"]
    assert engine.pool.checkedout() == 0
    db.close()
    engine.dispose()


def test_library_chat_uses_verified_free_chat_chain(monkeypatch):
    """La biblioteca va por la cadena gratuita de chat (OpenCode -> Groq ->
    Gemini): sin ella, un 403 de OpenCode degradaba cada análisis."""
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    import app.services.knowledge_chat as chat
    provider = Provider()
    monkeypatch.setattr(chat, "create_chat_llm_provider", lambda settings: provider)
    result = asyncio.run(ask_library(setup_library(), "repurchases", author="Buffett"))
    assert result["status"] == "ok"
    assert provider.request.task == "chat"


def test_degraded_analysis_message_does_not_claim_citations(monkeypatch):
    """Degradado honesto: sin modelo nada fue «citado»; se muestran los
    fragmentos relacionados y se dice que el análisis no está disponible."""
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    result = asyncio.run(ask_library(
        setup_library(), "repurchases", author="Buffett",
        mode="analisis", provider=Provider(fail=True)))
    assert result["status"] == "fragmentos"
    assert "no está disponible" in result["message"]
    assert "citados" not in result["message"]
    assert result["answers"] and all(a["text"] is None for a in result["answers"])


def test_chunk_id_como_cadena_se_acepta(monkeypatch):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    db = setup_library()
    chunk = retrieve(db, "repurchases", scope="letters", author="Buffett")[0][0][0]
    provider = Provider({"answers": [
        {"text": "Las recompras se valoran según el precio.", "chunk_id": str(chunk.id),
         "quote": "Repurchases can add value at sensible prices."}
    ]})
    result = asyncio.run(ask_library(db, "repurchases", author="Buffett", provider=provider))
    assert result["status"] == "ok"
    assert result["answers"][0]["citation"]["chunk_id"] == chunk.id


def test_respuestas_descartadas_en_verificacion_se_distinguen(monkeypatch):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    db = setup_library()
    provider = Provider({"answers": [
        {"text": "fake", "chunk_id": 99999, "quote": "Repurchases can add value at sensible prices."}
    ]})
    result = asyncio.run(ask_library(db, "repurchases", author="Buffett", provider=provider))
    assert result["status"] == "fragmentos"
    assert "no superaron la verificacion de citas" in result["message"]


def test_motivos_de_descarte_se_registran_sin_texto_ni_citas(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    db = setup_library()
    secret = "SECRETO-NO-DEBE-SALIR"
    provider = Provider({"answers": [
        "no es objeto",
        {"text": secret, "chunk_id": "x", "quote": secret},
        {"text": secret, "chunk_id": 99999, "quote": secret},
        {"text": secret, "chunk_id": 1, "quote": secret + " no esta en el chunk de origen"},
        {"text": "Compra 777 acciones", "chunk_id": 1,
         "quote": "Repurchases can add value at sensible prices."},
    ]})
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(ask_library(db, "repurchases", author="Buffett", provider=provider))
    assert "no superaron la verificacion de citas" in result["message"]
    line = next(r.getMessage() for r in caplog.records if "descartadas" in r.getMessage())
    for reason in ("item_no_objeto", "chunk_id_invalido", "chunk_id_no_enviado",
                   "cita_no_literal_o_longitud", "cifras_fuera_de_la_cita"):
        assert reason in line
    assert secret not in line and "777" not in line


def test_analysis_request_uses_registered_prompt_and_traces_it(monkeypatch):
    from app.services import prompt_registry

    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    provider = Provider()
    asyncio.run(ask_library(setup_library(), "repurchases", author="Buffett",
                            mode="analisis", provider=provider))
    resolved = prompt_registry.get_prompt("knowledge_analysis", allow_remote=False)
    assert provider.request.messages[0].content == resolved.text
    assert provider.request.metadata == resolved.trace_metadata()


def test_answer_request_uses_registered_prompt_and_traces_it(monkeypatch):
    from app.services import prompt_registry

    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "0")
    provider = Provider()
    asyncio.run(ask_library(setup_library(), "repurchases", author="Buffett", provider=provider))
    resolved = prompt_registry.get_prompt("knowledge_chat", allow_remote=False)
    assert provider.request.messages[0].content == resolved.text
    assert provider.request.metadata == resolved.trace_metadata()
