"""Library retrieval is doctrine, not company fact, and never trusts Qdrant prose."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, KnowledgeChunk, KnowledgeDocument, Tenant
from app.models.entities import Base
from app.services.chat_service import ChatService
from app.services.chat_synthesis_service import SECTION_SOURCE_TYPES
from app.services.library_context import retrieve_library_context
from app.services.rag import RAGIndex
from app.services.thesis_context import retrieve_thesis_context
from app.services.thesis_narrative_llm import evidence_sections


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="library-context", name="Test")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        document = KnowledgeDocument(title="Actual letter", author="Actual author", document_type="fund_letter", source_url="https://example.org/original", status="ready", language="en")
        session.add(document)
        session.flush()
        chunk = KnowledgeChunk(knowledge_document_id=document.id, chunk_index=0, content="Durable reinvestment runways matter.", qdrant_point_id="safe-point", page_number=2)
        company = Company(ticker="ASTS", name="AST", exchange="NASDAQ", currency="USD", sector="Telecom", industry="Satellites", company_type="growth", valuation_model="unassigned")
        session.add_all([chunk, company])
        session.commit()
        yield session, document, chunk, company


def hits(chunk):
    return [{"entity_type": "knowledge_chunk", "entity_id": chunk.id, "point_id": "safe-point", "text": "forged revenue 999", "title": "forged", "url": "https://evil.invalid"}]


def test_sql_identity_and_general_query(db, monkeypatch):
    session, document, chunk, _ = db
    calls = []
    def search(self, query, **kwargs):
        calls.append(kwargs)
        return hits(chunk) * 2 + [{"entity_type": "knowledge_chunk", "entity_id": True}]
    monkeypatch.setattr(RAGIndex, "search", search)
    rows = retrieve_library_context(session, "capital allocation")
    assert len(rows) == 1
    assert rows[0]["text"] == chunk.content
    assert rows[0]["url"] == document.source_url
    assert rows[0]["author"] == document.author
    assert rows[0]["evidence_role"] == "investment_doctrine_not_company_fact"
    assert calls[0]["ticker"] is None
    assert calls[0]["tenant_id"] == session.info["tenant_id"]


def test_fail_closed_wrong_tenant_point_deleted_and_not_ready(db, monkeypatch):
    session, document, chunk, _ = db
    monkeypatch.setattr(RAGIndex, "search", lambda *a, **k: hits(chunk))
    chunk.qdrant_point_id = "different"
    session.commit()
    assert retrieve_library_context(session, "q") == []
    chunk.qdrant_point_id = "safe-point"
    document.status = "failed"
    session.commit()
    assert retrieve_library_context(session, "q") == []
    document.status = "ready"
    session.commit()
    session.info["tenant_id"] = 999
    assert retrieve_library_context(session, "q") == []
    for bad in (None, True, 0, "1"):
        session.info["tenant_id"] = bad
        assert retrieve_library_context(session, "q") == []


def test_company_and_portfolio_chat_expose_cited_doctrine_only(db, monkeypatch):
    session, _, chunk, company = db
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_CHAT", "1")
    monkeypatch.setattr(RAGIndex, "search", lambda *a, **k: hits(chunk))
    service = ChatService()
    # Guarda intencional anti-ruido: una pregunta de ficha sin cue de doctrina no cita la biblioteca.
    plain = service._deterministic_answer(session, "Explain capital allocation", "company", company.ticker)
    assert not any(s["type"] == "knowledge_chunk" for s in plain.sources)
    for scope, ticker in (("company", company.ticker), ("portfolio", None)):
        response = service._deterministic_answer(session, "Explain Buffett capital allocation doctrine", scope, ticker)
        source = next(s for s in response.sources if s["type"] == "knowledge_chunk")
        assert source["id"] == chunk.id
        section = next(s for s in response.sections if s.key == "inferences")
        assert f"knowledge_chunk:{chunk.id}" in section.citations
        assert "not a company fact" in section.body
        assert "forged" not in section.body
    assert "knowledge_chunk" not in SECTION_SOURCE_TYPES["facts"]
    assert "knowledge_chunk" not in SECTION_SOURCE_TYPES["calculations"]
    assert "knowledge_chunk" in SECTION_SOURCE_TYPES["inferences"]


def test_thesis_has_distinct_library_identity(db, monkeypatch):
    session, _, chunk, company = db
    monkeypatch.setattr(RAGIndex, "search", lambda *a, **k: hits(chunk))
    context = retrieve_thesis_context(session, company)
    assert len(context) == 1
    assert context[0]["knowledge_document_id"] == chunk.knowledge_document_id
    text = evidence_sections([], context)["contexto_rag"]["parrafos"][0]
    assert "no es un dato financiero" in text
    assert "Biblioteca" in text
    assert "Documento None" not in text


def test_failure_is_empty(db, monkeypatch):
    def unavailable(*a, **k):
        raise RuntimeError("unavailable")
    monkeypatch.setattr(RAGIndex, "search", unavailable)
    assert retrieve_library_context(db[0], "q") == []


def test_library_search_filters_to_knowledge_chunks(db, monkeypatch):
    session, _document, _chunk, _ = db
    seen = {}

    def search(self, query, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(RAGIndex, "search", search)
    retrieve_library_context(session, "gestion de capital y recompra")
    assert seen["entity_type"] == "knowledge_chunk"


def test_query_filter_adds_entity_type_condition():
    flt = RAGIndex()._query_filter(None, 2, "knowledge_chunk")
    keys = {c.key: c.match.value for c in flt.must}
    assert keys == {"tenant_id": 2, "entity_type": "knowledge_chunk"}
    assert "entity_type" not in {c.key for c in RAGIndex()._query_filter(None, 2).must}
