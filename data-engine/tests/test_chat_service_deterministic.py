"""ChatService deterministic-baseline contract tests.

The deterministic answer is the honesty floor of research chat: it cites
only stored, sourced rows, states plainly what is missing, and proposes
the next data step instead of inventing content.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Claim,
    Company,
    FinancialFact,
    ThesisVersion,
)
from app.services.chat_service import ChatService, _decimal_to_float, _short


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_empty_company_is_blocked_with_honest_next_steps(db):
    company = _company(db)
    response = ChatService()._deterministic_answer(
        db, "What is the outlook for AAPL?", "company", "AAPL"
    )
    assert response.blocked is True
    assert response.model == "deterministic"
    # Prosa visible natural; el detalle estructurado queda en `sections`.
    assert "Todavía no tengo hechos financieros fiables almacenados" in response.answer
    assert "HECHO" not in response.answer
    facts_section = next(s for s in response.sections if s.key == "facts")
    assert "No hay hechos financieros fiables almacenados" in facts_section.body
    assert f"Crear la primera tesis para {company.ticker}" in response.proposed_actions
    assert any("Ingerir hechos financieros SEC/FMP" in action for action in response.proposed_actions)
    assert not response.sources


def test_populated_company_cites_stored_sourced_rows(db):
    company = _company(db)
    fact = FinancialFact(
        company_id=company.id, metric="revenue", value=Decimal("391000000000"),
        unit="USD", period="2025-09-27:FY", fiscal_year=2025,
        source_type="SEC", is_reported=True, confidence=Decimal("0.95"),
    )
    thesis = ThesisVersion(
        company_id=company.id, version=3, status="published",
        thesis_markdown="# t", executive_summary="e", rating="watch",
        current_price=Decimal("150"), expected_value=Decimal("200"),
    )
    db.add_all([fact, thesis])
    db.commit()

    response = ChatService()._deterministic_answer(
        db, "Revenue trend for AAPL?", "company", "AAPL"
    )
    assert response.blocked is False
    kinds = {source["type"] for source in response.sources}
    assert {"thesis_version", "financial_fact"} <= kinds
    fact_source = next(s for s in response.sources if s["type"] == "financial_fact")
    assert fact_source["source_type"] == "SEC"
    assert fact_source["value"] == 391000000000.0
    assert "Tengo guardada la tesis v3 (estado publicada, rating seguimiento)." in response.answer
    assert "ingresos 391 mil millones USD (ejercicio 2025, SEC)" in response.answer
    assert "Aun faltan datos almacenados de:" in response.answer  # other key metrics absent
    assert "efectivo y equivalentes" in response.answer  # cash_and_equivalents traducido


def test_unverified_claim_surfaces_review_action(db):
    company = _company(db)
    thesis = ThesisVersion(
        company_id=company.id, version=1, status="draft",
        thesis_markdown="# t", executive_summary="e",
    )
    claim = Claim(
        company_id=company.id, statement="Margins will expand next year",
        status="unverified", confidence=Decimal("0.5"), materiality_score=6,
    )
    db.add_all([thesis, claim])
    db.commit()

    response = ChatService()._deterministic_answer(db, "AAPL claims?", "company", "AAPL")
    assert "Revisar afirmaciones no verificadas o contradichas" in response.proposed_actions
    assert "Hay afirmaciones pendientes de verificar." in response.answer
    unverified = next(s for s in response.sections if s.key == "unverified_claims")
    assert "[unverified] Margins will expand next year" in unverified.body


def test_ticker_resolved_from_question_text(db):
    _company(db)
    service = ChatService()
    resolved = service._resolve_company(db, "How is aapl positioned?", "company", None)
    assert resolved is not None and resolved.ticker == "AAPL"
    assert service._resolve_company(db, "general question", "portfolio", None) is None


def test_helpers_compact_and_convert():
    assert _short("  hello\n\n  world  ") == "hello world"
    assert len(_short("x" * 1000, limit=10)) <= 13  # truncated with ellipsis marker
    assert _decimal_to_float(Decimal("1.5")) == 1.5
    assert _decimal_to_float(None) is None


def test_document_sources_preserve_stored_urls_without_inventing_missing_links(db, monkeypatch):
    from app.models.entities import Document, DocumentChunk

    company = _company(db)
    document = Document(company_id=company.id, title="Synthetic fixture", source_type="upload", source_url="https://example.org/fixture.pdf")
    db.add(document)
    db.flush()
    db.add(DocumentChunk(document_id=document.id, chunk_index=0, text="Fixture document revenue"))
    db.commit()
    monkeypatch.setattr(ChatService, "_rag_chunks", lambda *args, **kwargs: [{"point_id": "fixture-point", "title": "RAG fixture", "url": "https://example.org/rag.pdf", "text": "Fixture text"}])
    response = ChatService()._deterministic_answer(db, "revenue", "company", "AAPL")
    by_type = {source["type"]: source for source in response.sources}
    assert by_type["document_chunk"]["url"] == document.source_url
    assert by_type["rag_chunk"]["url"] == "https://example.org/rag.pdf"
    document.source_url = None
    db.commit()
    response = ChatService()._deterministic_answer(db, "revenue", "company", "AAPL")
    assert "url" not in next(source for source in response.sources if source["type"] == "document_chunk")


def test_thesis_status_source_entry_is_spanish_not_snake_case(db):
    company = _company(db)
    db.add(FinancialFact(
        company_id=company.id, metric="revenue", value=Decimal("1000000"),
        unit="USD", period="2025-12-31:FY", fiscal_year=2025, fiscal_quarter="FY",
        source_type="sec_xbrl",
    ))
    db.add(ThesisVersion(
        company_id=company.id, version=3, status="insufficient_data",
        thesis_markdown="...", executive_summary="...", rating="insufficient_data",
    ))
    db.commit()
    response = ChatService()._deterministic_answer(db, "AAPL tesis?", "company", "AAPL")
    thesis_sources = [s for s in response.sources if s["type"] == "thesis_version"]
    assert thesis_sources, "la tesis debe viajar como fuente"
    for source in thesis_sources:
        assert source.get("status") == "datos insuficientes"
        assert "insufficient_data" not in str(source.get("status"))


def test_library_doctrine_not_cited_in_company_answers(db, monkeypatch):
    """Cartas de la biblioteca fuera de las fuentes de una respuesta de empresa."""
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_CHAT", "1")
    from app.services import chat_service as cs

    fake = {"type": "knowledge_chunk", "id": 999, "chunk_id": 999, "knowledge_document_id": 1,
            "title": "Numantia Patrimonio - Carta 2020", "author": "Numantia Patrimonio",
            "year": 2020, "url": "https://example.com/carta", "source_type": "letter",
            "page_number": 3, "chunk_index": 0, "text": "Doctrina value...",
            "evidence_role": "investment_doctrine_not_company_fact"}
    monkeypatch.setattr(cs, "retrieve_library_context", lambda db_, q, limit=3: [fake])
    _company(db)
    resp = ChatService()._deterministic_answer(db, "Resume lo que tengo de AAPL", "company", "AAPL")
    assert all(src.get("type") != "knowledge_chunk" for src in resp.sources)


def test_library_doctrine_kept_for_doctrine_questions(db, monkeypatch):
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_CHAT", "1")
    from app.services import chat_service as cs

    calls = []

    def fake_retrieve(db_, q, limit=3, vector=None):
        calls.append(q)
        return []

    monkeypatch.setattr(cs, "retrieve_library_context", fake_retrieve)
    _company(db)
    ChatService()._deterministic_answer(db, "¿Qué diría Buffett de AAPL?", "company", "AAPL")
    assert calls, "una pregunta de doctrina sobre una empresa sí consulta la biblioteca"
