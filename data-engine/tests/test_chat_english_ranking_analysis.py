"""Chat en inglés (Ajustes → Idioma = English): ranking y análisis de la cartera.

Con el inglés elegido, «What's my biggest position?» acababa en «No puedo
responderte…» y «What are the risks of my portfolio?» respondía con las
cifras calculadas, pero en español. En español nada cambia.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, Position
from app.services.brain_context_tools import _risk_alert_en
from app.services.chat_service import ChatService


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _session(language: str):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = 1
    session.info["language"] = language
    for ticker, qty, cost, value in (("UBER", 30, 1500, 2400), ("ASTS", 100, 1200, 900), ("MSFT", 5, 1200, 1800)):
        comp = Company(ticker=ticker, name=f"{ticker} Inc", exchange="NYSE", company_type="platform",
                       valuation_model="unassigned")
        session.add(comp)
        session.flush()
        session.add(Position(
            tenant_id=1, company_id=comp.id, quantity=Decimal(qty), average_cost=Decimal(cost) / qty,
            market_value=Decimal(value), market_value_base=Decimal(value), cost_basis_base=Decimal(cost),
            currency="EUR", base_currency="EUR", as_of=date(2026, 10, 30),
        ))
    session.commit()
    return session


@pytest.fixture
def en():
    session = _session("en")
    yield session
    session.close()


@pytest.fixture
def es():
    session = _session("es")
    yield session
    session.close()


def _ask(db, question):
    return asyncio.run(ChatService().answer(db, question, "portfolio", None))


@pytest.mark.parametrize(("question", "expected"), [
    ("What's my biggest position?", "Your largest position by value is UBER: 2,400.00 €, 47.1% of your portfolio. "
                                    "Next is MSFT with 1,800.00 €."),
    ("What's my smallest holding?", "Your smallest position by value is ASTS: 900.00 €, 17.6% of your portfolio."),
    ("Which position weighs the most?", "Your heaviest position is UBER: 2,400.00 €, 47.1% of your portfolio."),
    ("Which holding has the lowest average cost?", "Your position with the lowest average cost is ASTS: 12.00 €. "
                                                   "Next is UBER with 50.00 €."),
])
def test_ranking_in_english(en, question, expected):
    resp = _ask(en, question)
    assert resp.llm_trace["path"] == "portfolio_ranking"
    assert resp.answer.startswith(expected)
    assert resp.sources[0]["title"].startswith("Position ")


@pytest.mark.parametrize("question", [
    "Analyze my portfolio",
    "How concentrated is my portfolio?",
    "What are the risks of my portfolio?",
    "How diversified is my portfolio?",
])
def test_analysis_in_english(en, question):
    resp = _ask(en, question)
    assert resp.llm_trace["path"] == "portfolio_analysis"
    assert resp.answer.startswith("Figures calculated from your saved positions (data as of Oct 30, 2026)")
    assert "- Largest position: UBER with 47.1% of the valued portfolio." in resp.answer
    assert "- Largest weights: UBER 47.1%, MSFT 35.3%, ASTS 17.6%." in resp.answer
    assert "- By sector: no sector 100%." in resp.answer
    assert "UBER is over 20% of the portfolio (severity high)." in resp.answer
    assert "Concentration: the largest position weighs 47.1% and the top 5 100.0%." in resp.answer
    for spanish in ("Cifras", "posición", "cartera", "gravedad", "Concentración", "sin sector"):
        assert spanish not in resp.answer


def test_spanish_unchanged(es):
    ranking = _ask(es, "¿Cuál es mi mayor posición?")
    assert ranking.answer == (
        "Tu posición con el valor más alto es UBER: 2.400,00 €, el 47,1 % de tu cartera. Le sigue MSFT con 1.800,00 €."
    )
    assert ranking.sources[0]["title"] == "Posición UBER"
    analysis = _ask(es, "¿Qué riesgos tiene mi cartera?")
    assert analysis.answer.startswith("Cifras calculadas de tus posiciones guardadas (datos a 30 oct 2026)")
    assert "UBER supera el 20 % de peso en la cartera (gravedad alta)." in analysis.answer
    # Sin el inglés, las frases en inglés no cambian de ruta.
    assert _ask(es, "Analiza mi cartera").llm_trace["path"] == "portfolio_overview"


def test_risk_alert_messages_in_english():
    assert _risk_alert_en("UBER supera el 20 % de peso en la cartera") == "UBER is over 20% of the portfolio"
    assert _risk_alert_en("ASTS es pre-FCF y supera el 10 % de peso en la cartera").startswith("ASTS is pre-FCF")
    assert _risk_alert_en("El saldo de caja en USD es negativo") == "The cash balance in USD is negative"
    assert _risk_alert_en(
        "El saldo neto de caja, convertido a EUR, es negativo (saldo negativo en USD (-10.00))"
    ) == "The net cash balance, converted to EUR, is negative (negative balance in USD (-10.00))"
    assert _risk_alert_en("otra regla") == "otra regla"
