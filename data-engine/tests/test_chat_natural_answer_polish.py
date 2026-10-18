"""Respuesta visible de empresa: sin claves internas, titulares limpios y
capitalizacion cuando el dato existe (hallazgo QA 4)."""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact, NewsEvent, ThesisVersion
from app.services.chat_service import ChatService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = "tenant-test"
    yield session
    session.close()


def _company(db):
    company = Company(
        ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ", currency="USD",
        sector="Telecom", industry="Satellites", company_type="growth",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _answer(db, question="ASTS precio y capitalización"):
    # Sin proveedor configurado la sintesis cae al baseline determinista:
    # es la respuesta visible que pulimos aqui.
    return asyncio.run(ChatService().answer(db, question, "portfolio", None))


def test_estado_y_rating_sin_claves_internas(db):
    company = _company(db)
    db.add(ThesisVersion(
        company_id=company.id, version=5, status="insufficient_data",
        thesis_markdown="...", executive_summary="...", rating="insufficient_data",
    ))
    db.commit()
    resp = _answer(db)
    assert "insufficient_data" not in resp.answer
    assert "datos insuficientes" in resp.answer
    assert "tesis v5" in resp.answer


def test_capitalizacion_cuando_hay_dato(db):
    company = _company(db)
    db.add(FinancialFact(
        company_id=company.id, metric="market_cap", value=Decimal("1140000000"),
        unit="USD", period="2025-12-31:FY", fiscal_year=2025, fiscal_quarter="FY",
        source_type="fmp",
    ))
    db.commit()
    resp = _answer(db)
    assert "Capitalización bursátil: 1,14 mil millones USD" in resp.answer


def test_titulares_sin_duplicar_ni_truncar(db):
    company = _company(db)
    largo = "AST SpaceMobile Advances Satellite Service Conversion With New Commercial Agreements Across Markets"
    db.add(NewsEvent(company_id=company.id, title=largo, date=date(2026, 10, 16), event_type="news"))
    db.add(NewsEvent(company_id=company.id, title=largo + " ", date=date(2026, 10, 16), event_type="news"))
    db.commit()
    resp = _answer(db)
    assert "Últimas noticias guardadas" in resp.answer
    assert resp.answer.count(largo) == 1
    assert "…" not in resp.answer and "..." not in resp.answer


def test_short_corta_en_palabra():
    from app.services.chat_service import _short
    out = _short("Have Opportunity to Lead the Class Action", 30)
    assert out.endswith("…")
    assert not out[:-1].endswith((" ",)) and "  " not in out
    ultimo = out[:-1].split(" ")[-1]
    assert ultimo in ["Have", "Opportunity", "to", "Lead", "the", "Class", "Action"]
