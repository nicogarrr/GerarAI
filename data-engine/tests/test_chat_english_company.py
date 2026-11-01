"""Chat en inglés (Ajustes → Idioma = English): ficha de una empresa.

Con el inglés elegido, «Tell me about ASTS» respondía en castellano
(«ASTS cotiza a…», «Datos almacenados: ingresos…», «Todavía no tengo hechos
financieros…»), y el aviso de que el modelo no responde también. Ahora la
misma respuesta determinista sale en inglés. En español nada cambia.
"""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import set_language_scope
from app.models.entities import Base, Company, FinancialFact, MarketPrice, NewsEvent
from app.services.chat_service import ChatService
from app.services.chat_synthesis_service import ChatSynthesisService


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _session(language: str, *, with_data: bool = True) -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    db.info["language"] = language
    for ticker in ("ASTS", "KO"):
        db.add(Company(ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ", currency="USD",
                       company_type="platform", valuation_model="unassigned"))
    db.flush()
    asts = db.query(Company).filter_by(ticker="ASTS").one()
    if with_data:
        db.add(FinancialFact(company_id=asts.id, metric="revenue", value=Decimal("4400000"), unit="USD",
                             period="2025-12-31:FY", fiscal_year=2025, source_type="filing"))
        db.add(FinancialFact(company_id=asts.id, metric="net_income", value=Decimal("-300000000"), unit="USD",
                             period="2025-12-31:FY", fiscal_year=2025, source_type="filing"))
        db.add(MarketPrice(company_id=asts.id, date=date(2026, 10, 29), open=Decimal("60"), high=Decimal("63"),
                           low=Decimal("59"), close=Decimal("61.23"), volume=1000, source="yahoo"))
        db.add(NewsEvent(tenant_id=1, company_id=asts.id, date=datetime(2026, 10, 27, tzinfo=UTC),
                         title="AST SpaceMobile files with the FCC", source="sec.gov", summary="s",
                         event_type="filing"))
    db.commit()
    return db


def _ask(db, question):
    token = set_language_scope(db.info["language"])
    try:
        return asyncio.run(ChatService().answer(db, question, "portfolio", None, use_jev=False))
    finally:
        from app.core.i18n import _request_language
        _request_language.reset(token)


def test_company_summary_in_english():
    db = _session("en")
    answer = _ask(db, "Tell me about ASTS").answer
    assert "ASTS trades at $61.23 (spot on Oct 29, 2026, source yahoo)." in answer
    assert "Stored data: revenue 4.4 million USD (FY 2025, filing); net income -300 million USD (FY 2025, filing)." in answer
    assert "Latest saved news: 'AST SpaceMobile files with the FCC' (Oct 27, 2026)." in answer
    for spanish in ("cotiza", "Datos almacenados", "ingresos", "noticias guardadas", "Aun faltan", "ejercicio"):
        assert spanish not in answer


def test_company_without_facts_in_english():
    db = _session("en", with_data=False)
    answer = _ask(db, "Tell me about ASTS").answer
    assert "I don't have reliable stored financial facts for ASTS yet; ingest its primary sources (SEC/FMP) and " \
        "I'll answer with figures." in answer
    assert "Still missing stored data for: revenue, free cash flow" in answer
    assert "Todavía" not in answer and "Aun faltan" not in answer


def test_company_metric_lead_in_english():
    db = _session("en")
    answer = _ask(db, "What is the revenue of ASTS?").answer
    assert answer.startswith("ASTS revenue: 4.4 million USD (FY 2025, filing).")


def test_spanish_company_answer_unchanged():
    db = _session("es")
    answer = _ask(db, "Háblame de ASTS").answer
    assert "ASTS cotiza a $61.23 (spot del 29 oct 2026, fuente yahoo)." in answer
    assert "Datos almacenados: ingresos 4,4 millones USD (ejercicio 2025, filing)" in answer


def test_general_fallback_in_english():
    base = asyncio.run(ChatService().answer(_session("en"), "Tell me about ASTS", "portfolio", None, use_jev=False))
    token = set_language_scope("en")
    try:
        text = ChatSynthesisService._general_fallback(base, reason="error").answer
        quota = ChatSynthesisService._general_fallback(base, reason="quota").answer
    finally:
        from app.core.i18n import _request_language
        _request_language.reset(token)
    assert text == "I can't answer with sources right now; try again in a moment or give me a ticker to go to specific data."
    assert quota.startswith("The configured model has reached its usage limit")
    es = ChatSynthesisService._general_fallback(base, reason="error").answer
    assert es.startswith("No puedo responderte con fuentes ahora mismo")
