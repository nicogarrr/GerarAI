"""Chat: «¿cuántas operaciones he hecho?» / «how many trades did I make?» con un recuento.

Antes la pregunta caía al modelo general («No puedo responderte con fuentes…»)
y en inglés «how many trades have I made this year?» contestaba con el bloque
fiscal. Ahora cuenta tus compras y ventas guardadas, por año y, con varias
carteras, por cartera. Solo lectura y solo del tenant.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, Portfolio, Transaction
from app.services import brain_account_tools
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el recuento no debe pasar por el LLM")


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 11, 2))


def _db(two_portfolios=False, empty=False):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ids = {}
    for ticker in ("KO", "ITX", "TSLA"):
        company = Company(
            ticker=ticker,
            name=ticker + " Inc",
            exchange="NYSE",
            company_type="consumer",
            valuation_model="unassigned",
            currency="USD",
        )
        db.add(company)
        db.flush()
        ids[ticker] = company.id
    trades = {
        1: ()
        if empty
        else (
            ("KO", "buy", date(2026, 10, 5)),
            ("ITX", "buy", date(2026, 9, 12)),
            ("KO", "sell", date(2026, 3, 1)),
            ("KO", "buy", date(2025, 6, 1)),
            ("KO", "dividend", date(2026, 10, 20)),
        ),
        2: (
            ("TSLA", "buy", date(2026, 10, 7)),
            ("TSLA", "sell", date(2026, 10, 8)),
            ("TSLA", "buy", date(2024, 1, 8)),
        ),
    }
    for tenant, rows in trades.items():
        db.info["tenant_id"] = tenant
        main = Portfolio(tenant_id=tenant, name="Principal", base_currency="EUR", is_default=True)
        db.add(main)
        db.flush()
        other = None
        if two_portfolios and tenant == 1:
            other = Portfolio(tenant_id=tenant, name="Hijos", base_currency="EUR")
            db.add(other)
            db.flush()
        for ticker, action, day in rows:
            portfolio = other if other is not None and ticker == "ITX" else main
            db.add(
                Transaction(
                    tenant_id=tenant,
                    portfolio_id=portfolio.id,
                    company_id=ids[ticker],
                    trade_date=day,
                    action=action,
                    quantity=Decimal("0" if action == "dividend" else "1"),
                    price=Decimal("10"),
                    currency="USD",
                )
            )
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize(
    "question",
    [
        "¿Cuántas operaciones he hecho?",
        "cuantas compras y ventas he hecho",
        "¿Cuántas operaciones tengo registradas?",
    ],
)
def test_count_all(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_trade_count"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.splitlines() == [
        "Tienes 4 operaciones de compraventa guardadas: 3 compras y 1 venta.",
        "- 2026: 3 (2 compras y 1 venta)",
        "- 2025: 1 (1 compra)",
        "Cuento compras y ventas; no dividendos ni movimientos de efectivo.",
    ]


def test_count_this_year():
    resp = _ask(_db(), "¿Cuántas operaciones hice este año?")
    assert resp.llm_trace["path"] == "account_trade_count"
    assert (
        resp.answer.splitlines()[0]
        == "En 2026 tienes 3 operaciones de compraventa guardadas: 2 compras y 1 venta."
    )


def test_count_period_empty():
    resp = _ask(_db(), "¿cuántas operaciones he hecho este mes?")
    assert resp.answer == "No hay compras ni ventas guardadas de noviembre de 2026."


def test_count_empty_account():
    resp = _ask(_db(empty=True), "¿cuántas operaciones he hecho?")
    assert resp.answer == "No tienes compras ni ventas guardadas. Puedes importarlas en Cartera."


def test_count_by_portfolio():
    resp = _ask(_db(two_portfolios=True), "¿cuántas operaciones he hecho?")
    assert "Por cartera: Principal 3, Hijos 1." in resp.answer.splitlines()


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿cuántas operaciones he hecho?")
    assert resp.answer.splitlines()[:3] == [
        "Tienes 3 operaciones de compraventa guardadas: 2 compras y 1 venta.",
        "- 2026: 2 (1 compra y 1 venta)",
        "- 2024: 1 (1 compra)",
    ]


def test_ticker_question_is_not_a_count():
    resp = _ask(_db(), "¿Cuántas operaciones he hecho con KO?")
    assert (resp.llm_trace or {}).get("path") != "account_trade_count"


@pytest.mark.parametrize("question", ["How many trades did I make?", "how many trades have I made?"])
def test_english(monkeypatch, question):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, question)
    finally:
        get_settings.cache_clear()
    assert resp.llm_trace["path"] == "account_trade_count"
    assert resp.answer.splitlines() == [
        "You have 4 saved buys and sells: 3 buys and 1 sell.",
        "- 2026: 3 (2 buys and 1 sell)",
        "- 2025: 1 (1 buy)",
        "Counting buys and sells only; not dividends or cash movements.",
    ]


def test_english_this_year_is_not_the_tax_block(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "How many trades have I made this year?")
    finally:
        get_settings.cache_clear()
    assert resp.llm_trace["path"] == "account_trade_count"
    assert resp.answer.splitlines()[0] == "In 2026 you have 3 saved buys and sells: 2 buys and 1 sell."
