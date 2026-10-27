"""El Cerebro encuentra la respuesta dentro de un 10-K largo (pregunta en castellano)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, Document, DocumentChunk
from app.models.entities import Base
from app.services.chat_service import ChatService, _prune_sources
from app.services.filing_passages import company_passages, is_xbrl_header, query_terms

XBRL = (
    "2025-12-310001819994us-gaap:EmployeeStockMember2025-01-012025-12-310001819994rklb:A2021"
    "EmployeeStockPurchasePlanMember2021-08-310001819994us-gaap:RestrictedStockUnitsRSUMember"
    "2024-12-310001819994us-gaap:SegmentMember2025-12-310001819994rklb:LaunchMember2025-12-31"
    "0001819994us-gaap:EmployeeStockMember2024-12-310001819994"
)
FILLER = (
    "The Company designs and manufactures launch vehicles and spacecraft components. "
    "Results may vary from period to period due to many factors outside of our control. "
)
EMPLOYEES = (
    "Human Capital. As of December 31, 2025, we had over 2,600 full-time permanent employees "
    "worldwide. Our employees are not subject to collective bargaining agreements."
)
SUPPLIERS = (
    "We regularly evaluate supplier relationships. Our largest suppliers include Pentair plc, "
    "Zodiac Pool Systems, Inc. and Hayward Holdings, Inc."
)


@pytest.fixture()
def db():
    session = Session(create_engine("sqlite://"))
    Base.metadata.create_all(session.get_bind())
    company = Company(
        ticker="RKLB",
        name="Rocket Lab Corporation",
        exchange="NASDAQ",
        currency="USD",
        sector="x",
        industry="x",
        company_type="operating",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    session.add(company)
    session.flush()
    document = Document(
        company_id=company.id,
        title="RKLB 10-K 2026-02-26",
        source_type="SEC",
        source_url="https://www.sec.gov/Archives/edgar/data/1819994/rklb-20251231.htm",
        published_at=datetime(2026, 2, 26, tzinfo=UTC),
    )
    session.add(document)
    session.flush()
    texts = [XBRL] * 10 + [FILLER * 12] * 140
    texts[120] = FILLER * 6 + EMPLOYEES + " " + FILLER * 4
    texts[131] = FILLER * 3 + SUPPLIERS + " " + FILLER * 8
    for index, text in enumerate(texts):
        session.add(DocumentChunk(document_id=document.id, chunk_index=index, text=text))
    session.commit()
    return session


def test_cabecera_xbrl_no_es_un_pasaje():
    assert is_xbrl_header(XBRL)
    assert not is_xbrl_header(EMPLOYEES)


def test_pregunta_en_castellano_se_traduce_a_terminos_del_filing(db):
    company = db.query(Company).one()
    terms = query_terms("¿Cuántos empleados tiene Rocket Lab?", company)
    assert "employees" in terms
    # El nombre de la empresa sale en todo el 10-K: no discrimina.
    assert "rocket" not in terms and "lab" not in terms


def test_la_respuesta_mas_alla_del_fragmento_80_se_encuentra(db):
    company = db.query(Company).one()
    passages = company_passages(db, company, "¿Cuántos empleados tiene Rocket Lab?")
    assert passages, "sin pasajes"
    best = passages[0]
    assert best.chunk.chunk_index == 120
    # El pasaje es la ventana con la respuesta, no los 240 primeros caracteres.
    assert "2,600 full-time permanent employees" in best.text
    assert len(best.text) <= 910
    assert all(not is_xbrl_header(p.chunk.text) for p in passages)


def test_proveedores_principales(db):
    company = db.query(Company).one()
    passages = company_passages(db, company, "¿Quiénes son los principales proveedores?")
    assert passages[0].chunk.chunk_index == 131
    assert "Pentair" in passages[0].text


def test_el_chat_pasa_el_pasaje_al_contexto(db):
    db.info["tenant_id"] = None
    response = ChatService(provider=object())._deterministic_answer(  # type: ignore[arg-type]
        db, "¿Cuántos empleados tiene Rocket Lab?", "company", "RKLB"
    )
    chunks = [s for s in response.sources if s.get("type") == "document_chunk"]
    assert chunks, response.sources
    assert "2,600" in chunks[0]["text"]


def test_poda_conserva_pasajes_distintos_del_mismo_documento():
    sources = [
        {"type": "document_chunk", "id": 1, "title": "RKLB 10-K", "text": "a"},
        {"type": "document_chunk", "id": 2, "title": "RKLB 10-K", "text": "b"},
        {"type": "financial_fact", "id": 3, "title": "Ingresos (FY 2025)"},
        {"type": "financial_fact", "id": 4, "title": "Ingresos (FY 2025)"},
    ]
    sections = [
        {"citations": ["document_chunk:1", "document_chunk:2", "financial_fact:3", "financial_fact:4"]}
    ]
    kept = _prune_sources(sources, sections, "")
    assert [s["id"] for s in kept] == [1, 2, 3]
