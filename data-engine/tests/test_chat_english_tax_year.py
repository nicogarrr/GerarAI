"""Chat en inglés (Ajustes → Idioma = English): resumen fiscal de un ejercicio.

Con el inglés elegido, «How much tax did I pay in 2025?» o «What are my
capital gains this year?» acababan en «No puedo responderte con fuentes…».
Ahora responden con el mismo resumen del informe fiscal que en español,
en inglés. En español nada cambia.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.local_date import local_today
from app.models.entities import Base, Company, FXRate, Position, Transaction
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
    companies = {}
    for ticker in ("UBER", "KO"):
        comp = Company(ticker=ticker, name=f"{ticker} Inc", exchange="NYSE", company_type="platform",
                       valuation_model="unassigned", currency="USD")
        session.add(comp)
        session.flush()
        companies[ticker] = comp

    def tx(ticker, day, action, qty, price, fees="0"):
        session.add(Transaction(tenant_id=1, company_id=companies[ticker].id, trade_date=day, action=action,
                                quantity=Decimal(qty), price=Decimal(price), fees=Decimal(fees), currency="USD"))

    tx("UBER", date(2024, 3, 1), "buy", 40, "50", "1")
    tx("UBER", date(2025, 6, 1), "sell", 10, "80", "1")
    tx("KO", date(2025, 4, 1), "dividend", 1, "9.20")
    session.add(Position(
        tenant_id=1, company_id=companies["UBER"].id, quantity=Decimal(30), average_cost=Decimal(50),
        market_value=Decimal(2400), market_value_base=Decimal(2400), cost_basis_base=Decimal(1500),
        currency="EUR", base_currency="EUR", as_of=date(2026, 10, 30),
    ))
    day = date(2023, 12, 1)
    while day <= date(2025, 12, 31):
        session.add(FXRate(tenant_id=1, base_currency="EUR", quote_currency="USD", rate=Decimal("0.9"),
                           rate_date=day, source="ecb"))
        day += timedelta(days=1)
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


_EN_2025 = (
    "Your tax data in GerarAI (Taxes):\n"
    "- Tax year 2025: gross dividends 8.28 EUR; withholding at source 0.00 EUR; realized gain/loss 268.88 EUR; "
    "blocked losses (two-month rule) 0.00 EUR; estimated savings income base 277.16 EUR. Draft, not tax advice."
)


@pytest.mark.parametrize("question", [
    "How much tax did I pay in 2025?",
    "What are my taxes for 2025?",
    "What are my capital gains for 2025?",
    "How much did I make in 2025?",
])
def test_tax_year_in_english(en, question):
    resp = _ask(en, question)
    assert resp.llm_trace["path"] == "personal_context"
    assert resp.llm_trace["intent"] == "fiscal"
    assert resp.answer == _EN_2025
    assert resp.sources[0]["title"] == "Tax report 2025"


def test_this_and_last_year_in_english(en):
    this_year = local_today().year
    assert f"- Tax year {this_year}:" in _ask(en, "What are my capital gains this year?").answer
    assert f"- Tax year {this_year - 1}:" in _ask(en, "My tax summary for last year").answer


def test_unrealized_gains_stay_performance(en):
    assert _ask(en, "What are my unrealized gains?").llm_trace["path"] == "portfolio_performance"


def test_spanish_unchanged(es):
    resp = _ask(es, "¿Cuánto IRPF pagué en 2025?")
    assert resp.answer == (
        "Tus datos de fiscal en GerarAI:\n"
        "- Ejercicio 2025: dividendos brutos 8,28 EUR; retenciones en origen 0,00 EUR; ganancia/pérdida realizada "
        "268,88 EUR; pérdidas bloqueadas (regla de 2 meses) 0,00 EUR; base del ahorro estimada 277,16 EUR. "
        "Borrador, no asesoría fiscal."
    )
    assert resp.sources[0]["title"] == "Informe fiscal 2025"
    # La frase en inglés sin el inglés elegido no cambia de ruta.
    assert _ask(es, "How much tax did I pay in 2025?").llm_trace.get("intent") != "fiscal"
