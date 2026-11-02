"""Chat: «mis últimas operaciones» / «¿qué compré el mes pasado?» con tus operaciones guardadas.

Antes estas preguntas caían al modelo general, que sin fuentes contestaba «No
puedo responderte con fuentes ahora mismo»: el chat no leía tus compras y
ventas guardadas salvo para ventas e impuestos. Ahora las lista, la más
reciente primero, con fecha, cantidad, precio en la divisa de la operación y
cartera. Solo lectura y solo del tenant.
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
        raise AssertionError("las operaciones no deben pasar por el LLM")


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 11, 2))


def _db(two_portfolios=False):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ids = {}
    for ticker, currency in (("KO", "USD"), ("ITX", "EUR"), ("TSLA", "USD")):
        company = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="consumer",
                          valuation_model="unassigned", currency=currency)
        db.add(company)
        db.flush()
        ids[ticker] = company.id
    trades = {
        1: (("KO", "buy", date(2026, 10, 5), "10", "60.5", "USD"),
            ("ITX", "buy", date(2026, 9, 12), "3", "45.2", "EUR"),
            ("KO", "sell", date(2025, 6, 1), "2", "58", "USD"),
            ("KO", "dividend", date(2026, 10, 20), "0", "5.1", "USD")),
        2: (("TSLA", "buy", date(2026, 10, 7), "1", "250", "USD"),),
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
        for ticker, action, day, qty, price, currency in rows:
            portfolio = other if other is not None and ticker == "ITX" else main
            db.add(Transaction(tenant_id=tenant, portfolio_id=portfolio.id, company_id=ids[ticker], trade_date=day,
                               action=action, quantity=Decimal(qty), price=Decimal(price), currency=currency))
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["mis últimas operaciones", "¿Cuál fue mi última operación?",
                                      "¿Qué operaciones he hecho?"])
def test_recent_trades(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_trades"
    assert resp.llm_trace["provider_calls"] == 0
    lines = resp.answer.splitlines()
    assert lines[0] == "Tus últimas compras y ventas guardadas (la más reciente primero):"
    assert lines[1] == "- 5 oct 2026: compra de 10 KO a 60,50 USD."
    assert lines[2] == "- 12 sept 2026: compra de 3 ITX a 45,20 EUR."
    assert lines[3] == "- 1 jun 2025: venta de 2 KO a 58,00 USD."
    assert "5,10" not in resp.answer  # un dividendo no es una compraventa
    assert "TSLA" not in resp.answer


def test_last_month():
    resp = _ask(_db(), "¿Qué compré el mes pasado?")
    assert resp.llm_trace["path"] == "account_trades"
    assert resp.answer.splitlines() == ["Tus compras guardadas de octubre de 2026:",
                                        "- 5 oct 2026: compra de 10 KO a 60,50 USD."]


def test_this_year():
    resp = _ask(_db(), "¿qué operaciones hice este año?")
    assert resp.llm_trace["path"] == "account_trades"
    assert resp.answer.splitlines()[0] == "Tus compras y ventas guardadas de 2026:"
    assert "venta de 2 KO" not in resp.answer


def test_empty_period():
    resp = _ask(_db(), "¿Qué he comprado este mes?")
    assert resp.llm_trace["path"] == "account_trades"
    assert resp.answer == "No hay compras guardadas de noviembre de 2026."


def test_two_portfolios_name_each():
    resp = _ask(_db(two_portfolios=True), "mis últimas operaciones")
    assert "- 5 oct 2026: compra de 10 KO a 60,50 USD (Principal)." in resp.answer
    assert "- 12 sept 2026: compra de 3 ITX a 45,20 EUR (Hijos)." in resp.answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        db = _db()
        db.info["language"] = "en"
        resp = _ask(db, "what did I buy last month?")
        recent = _ask(db, "my recent trades")
    finally:
        get_settings.cache_clear()
    assert resp.llm_trace["path"] == "account_trades"
    assert resp.answer.splitlines() == ["Your saved buys in October 2026:",
                                        "- Oct 5, 2026: bought 10 KO at 60.50 USD."]
    assert recent.answer.splitlines()[0] == "Your latest saved buys and sells (most recent first):"
    assert "- Jun 1, 2025: sold 2 KO at 58.00 USD." in recent.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "mis últimas operaciones")
    assert resp.llm_trace["path"] == "account_trades"
    assert "TSLA" in resp.answer
    for leak in ("KO", "ITX", "60,50"):
        assert leak not in resp.answer


@pytest.mark.parametrize("question", ["¿qué compro ahora?", "¿Es buena idea que compre más?", "¿Qué he vendido este año?"])
def test_not_this_answer(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace.get("path") != "account_trades"
