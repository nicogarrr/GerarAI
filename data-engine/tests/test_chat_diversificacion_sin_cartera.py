"""Chat: «¿qué diversificación tengo?» / «which sectors am I in?» y «how many positions do I have?».

Antes, sin «mi cartera» en la frase, estas preguntas caían al modelo general,
que sin fuentes contestaba «No puedo responderte con fuentes ahora mismo».
Ahora van al análisis calculado de la cartera (mayor posición, reparto por
sector y por divisa, panel de riesgo) o al resumen de posiciones. Solo
lectura y solo del tenant.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, Position
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el análisis de cartera no debe pasar por el LLM")


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _db(language="es"):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    holdings = {1: (("UBER", "Technology", 2400), ("MSFT", "Technology", 1800), ("KO", "Consumer", 900)),
                2: (("TSLA", "Auto", 5000),)}
    for tenant, rows in holdings.items():
        db.info["tenant_id"] = tenant
        for ticker, sector, value in rows:
            comp = Company(ticker=ticker, name=f"{ticker} Inc", exchange="NYSE", company_type="platform",
                           valuation_model="unassigned", sector=sector)
            db.add(comp)
            db.flush()
            db.add(Position(tenant_id=tenant, company_id=comp.id, quantity=Decimal(10),
                            average_cost=Decimal(value) / 10, market_value=Decimal(value),
                            market_value_base=Decimal(value), cost_basis_base=Decimal(value),
                            currency="USD", base_currency="EUR", as_of=date(2026, 10, 30)))
        db.commit()
    db.info["tenant_id"] = 1
    db.info["language"] = language
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Qué diversificación tengo?", "¿En qué sectores estoy?",
                                      "¿Cuánta diversificación tengo?", "¿En qué sectores invierto?"])
def test_spanish_exposure_goes_to_analysis(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "portfolio_analysis"
    assert "- Mayor posición: UBER" in resp.answer
    assert "Technology" in resp.answer and "USD" in resp.answer


@pytest.mark.parametrize("question", ["What's my diversification?", "Which sectors am I in?",
                                      "What currencies am I exposed to?", "How diversified am I?"])
def test_english_exposure_goes_to_analysis(question):
    resp = _ask(_db("en"), question)
    assert resp.llm_trace["path"] == "portfolio_analysis"
    assert "- Largest position: UBER" in resp.answer
    assert "Technology" in resp.answer and "USD" in resp.answer


@pytest.mark.parametrize("question", ["How many positions do I have?", "how many stocks do I own?"])
def test_english_position_count(question):
    resp = _ask(_db("en"), question)
    assert resp.llm_trace["path"] == "portfolio_overview"
    assert "3 open positions" in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿En qué sectores estoy?")
    assert resp.llm_trace["path"] == "portfolio_analysis"
    assert "TSLA" in resp.answer
    for leak in ("UBER", "MSFT", "KO", "Technology"):
        assert leak not in resp.answer


def test_ticker_question_is_not_the_portfolio():
    resp = _ask(_db(), "¿En qué sectores está MSFT?")
    assert resp.llm_trace.get("path") != "portfolio_analysis"
