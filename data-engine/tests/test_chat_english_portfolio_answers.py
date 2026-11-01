"""Chat en inglés (Ajustes → Idioma = English): respuestas fijas de cartera.

Con el inglés elegido, «How many UBER shares do I have?» o «What's my average
cost on UBER?» caían en el volcado de la empresa («Todavía no tengo hechos
financieros fiables…») y las respuestas de posición y rentabilidad salían
siempre en español. En español nada cambia.
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
    session.add(Company(ticker="KO", name="Coca-Cola", exchange="NYSE", company_type="platform",
                        valuation_model="unassigned"))
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


@pytest.mark.parametrize("question", [
    "How many UBER shares do I have?",
    "How many shares of UBER do I own?",
    "What's my average cost on UBER?",
    "What is my average price for UBER?",
    "What's the weight of UBER in my portfolio?",
    "How much is UBER of my portfolio?",
    "What's my position in UBER?",
])
def test_position_questions_in_english(en, question):
    resp = _ask(en, question)
    assert resp.llm_trace["path"] == "portfolio_position"
    assert resp.answer == (
        "Your saved position in UBER: 30 shares, average cost 50.00 €, value 2,400.00 €, "
        "47.1% of the value of your positions, as of Oct 30, 2026."
    )


def test_position_not_held_in_english(en):
    resp = _ask(en, "How many shares of KO do I have?")
    assert resp.llm_trace["path"] == "portfolio_position"
    assert resp.answer == "You have no saved position in KO; your saved portfolio has 3 open positions in other tickers."


@pytest.mark.parametrize(("question", "label", "pct"), [
    ("What's my return on UBER?", "your position in UBER", "+60%"),
    ("How much have I made on UBER?", "your position in UBER", "+60%"),
    ("What's my profit on MSFT?", "your position in MSFT", "+50%"),
    ("How much have I gained overall?", "your portfolio", "+30.77%"),
])
def test_return_questions_in_english(en, question, label, pct):
    resp = _ask(en, question)
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert resp.answer.startswith(f"The saved return on {label} is {pct} on the purchase cost: ")
    assert "not a time-weighted return (TWR)" in resp.answer
    assert "rentabilidad" not in resp.answer


def test_return_with_a_condition_is_not_the_saved_figure(en):
    resp = _ask(en, "How much would I have made on UBER if I had sold in March?")
    assert resp.llm_trace.get("path") != "portfolio_performance"


def test_spanish_questions_with_english_picked_answer_in_english(en):
    resp = _ask(en, "¿Cuántas acciones tengo de UBER?")
    assert resp.answer.startswith("Your saved position in UBER: 30 shares")


def test_spanish_is_unchanged(es):
    resp = _ask(es, "¿Cuántas acciones tengo de UBER?")
    assert resp.answer == (
        "Tu posición guardada en UBER: 30 acciones, coste medio 50,00 €, valor 2.400,00 €, "
        "un 47,1 % del valor de tus posiciones, con datos a 30 oct 2026."
    )
    resp = _ask(es, "¿Cuánto me ha rentado UBER?")
    assert resp.answer.startswith("La rentabilidad guardada de tu posición en UBER es +60 % sobre el coste de compra")
    # Las frases en inglés no cambian el enrutado en español.
    assert _ask(es, "How many UBER shares do I have?").llm_trace.get("path") != "portfolio_position"
