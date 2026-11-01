"""Chat en inglés (Ajustes → Idioma = English): dividendos de la cartera.

«How much MSFT dividends have I received?» daba los dividendos declarados de
la empresa (no lo cobrado con tu posición) y en español; «What dividends have
I received this year?» no encontraba respuesta. En español nada cambia.
"""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import reset_language_scope, set_language_scope
from app.models.entities import Base, Company, DividendRecord, Position
from app.services.brain_data_tools import _dividend_answer
from app.services.chat_service import ChatService

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db(monkeypatch):
    import app.core.local_date as local_date

    monkeypatch.setattr(local_date, "_utc_now", lambda: NOW)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = 1
    companies = {}
    for ticker, name in (("KO", "Coca-Cola"), ("MSFT", "Microsoft"), ("PEP", "PepsiCo")):
        company = Company(ticker=ticker, name=name, currency="USD", exchange="NYSE",
                          company_type="operating", valuation_model="unassigned")
        session.add(company)
        session.flush()
        companies[ticker] = company
    for ticker, qty in (("KO", "10"), ("MSFT", "4")):
        session.add(Position(tenant_id=1, company_id=companies[ticker].id, quantity=Decimal(qty),
                             average_cost=Decimal("50"), currency="USD"))
    for ticker, amount, ex in (("KO", "0.51", date(2026, 3, 13)), ("MSFT", "0.83", date(2026, 3, 13)),
                               ("MSFT", "0.75", date(2025, 8, 20)), ("PEP", "1.35", date(2026, 3, 13))):
        session.add(DividendRecord(company_id=companies[ticker].id, tenant_id=1, ex_date=ex,
                                   amount=Decimal(amount), currency="USD", source="fmp"))
    session.commit()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def english():
    token = set_language_scope("en")
    yield
    reset_language_scope(token)


@pytest.mark.parametrize("question", [
    "How much MSFT dividends have I received?",
    "How much in dividends have I received from Microsoft this year?",
])
def test_named_company_dividends_received_in_english(db, english, question):
    response = _dividend_answer(db, question, 1)
    assert response is not None
    assert response.llm_trace["path"] == "portfolio_dividends"
    assert response.answer.startswith("Saved declared dividends from your open positions in 2026")
    assert "- MSFT: 1 payment in 2026, $3.32 (4.00 shares" in response.answer
    assert "Total: $3.32." in response.answer
    assert "KO" not in response.answer


def test_portfolio_dividends_this_year_and_last_year_in_english(db, english):
    response = _dividend_answer(db, "What dividends have I received this year?", 1)
    assert response is not None
    assert "- KO: 1 payment in 2026, $5.10" in response.answer
    assert "Total: $8.42." in response.answer
    last = _dividend_answer(db, "What dividends did I receive last year?", 1)
    assert last is not None
    assert "- MSFT: 1 payment in 2025, $3.00" in last.answer
    assert "No saved dividends: KO." in last.answer


def test_not_held_company_in_english(db, english):
    response = _dividend_answer(db, "How much PEP dividends have I received?", 1)
    assert response is not None
    assert response.answer.startswith("You don't hold PEP in your portfolio right now")


def test_company_dividends_in_english(db, english):
    response = _dividend_answer(db, "When does PEP pay dividends?", 1)
    assert response is not None
    assert response.llm_trace["path"] == "company_dividends"
    assert "**Saved dividends for PEP · PepsiCo**" in response.answer
    assert "Last paid (saved): PEP: $1.35 per share, ex-dividend Mar 13, 2026" in response.answer


def test_chat_routes_the_english_question(db):
    db.info["language"] = "en"
    response = asyncio.run(ChatService().answer(db, "How much MSFT dividends have I received?", "portfolio", None))
    assert response.llm_trace["path"] == "portfolio_dividends"
    assert "MSFT: 1 payment in 2026" in response.answer


def test_spanish_is_unchanged(db):
    response = _dividend_answer(db, "¿Cuántos dividendos he cobrado de MSFT?", 1)
    assert response is not None
    assert "MSFT: 1 pago(s) en 2026, $3.32 (4,00 acciones" in response.answer
    # Sin «cobrado» ni «mis dividendos», en español sigue siendo la ficha de la empresa.
    company = _dividend_answer(db, "How much MSFT dividends have I received?", 1)
    assert company is not None and company.llm_trace["path"] == "company_dividends"
    assert "Dividendos guardados de MSFT" in company.answer
