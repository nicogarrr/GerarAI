"""Chat: «¿cuándo compré KO?» / «when did I buy KO?» lista tus operaciones de esa empresa.

Antes «¿cuándo compré KO?» contestaba con los datos financieros de la empresa
(«Todavía no tengo hechos financieros fiables…») y «when did I buy KO?» con
«I don't place orders…», como si fuera una orden. Ahora lista tus compras y
ventas guardadas de ese ticker. Solo lectura y solo del tenant.
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


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ids = {}
    for ticker in ("KO", "ITX"):
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
        1: (
            ("KO", "buy", date(2026, 10, 5), "10", "60.5"),
            ("ITX", "buy", date(2026, 9, 12), "3", "45.2"),
            ("KO", "sell", date(2025, 6, 1), "2", "58"),
        ),
        2: (("KO", "buy", date(2026, 10, 7), "999", "1"),),
    }
    for tenant, rows in trades.items():
        db.info["tenant_id"] = tenant
        p = Portfolio(tenant_id=tenant, name="Principal", base_currency="EUR", is_default=True)
        db.add(p)
        db.flush()
        for ticker, action, day, qty, price in rows:
            db.add(
                Transaction(
                    tenant_id=tenant,
                    portfolio_id=p.id,
                    company_id=ids[ticker],
                    trade_date=day,
                    action=action,
                    quantity=Decimal(qty),
                    price=Decimal(price),
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
    ["¿Cuándo compré KO?", "mis operaciones de KO", "¿Qué operaciones he hecho con KO?", "¿cuándo vendí KO?"],
)
def test_ticker_trades(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") == "account_trades"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.splitlines() == [
        "Tus compras y ventas guardadas de KO (la más reciente primero):",
        "- 5 oct 2026: compra de 10 KO a 60,50 USD.",
        "- 1 jun 2025: venta de 2 KO a 58,00 USD.",
    ]


def test_ticker_without_trades():
    resp = _ask(_db(), "¿Cuándo compré MSFT?")
    assert (resp.llm_trace or {}).get("path") == "account_trades"
    assert resp.answer == "No tienes compras ni ventas guardadas de MSFT."


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuándo compré KO?")
    assert "999" in resp.answer
    assert "60,50" not in resp.answer


@pytest.mark.parametrize("question", ["When did I buy KO?", "my KO trades"])
def test_english(monkeypatch, question):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, question)
    finally:
        get_settings.cache_clear()
    assert (resp.llm_trace or {}).get("path") == "account_trades"
    assert resp.answer.splitlines() == [
        "Your saved buys and sells of KO (most recent first):",
        "- Oct 5, 2026: bought 10 KO at 60.50 USD.",
        "- Jun 1, 2025: sold 2 KO at 58.00 USD.",
    ]


@pytest.mark.parametrize(
    "question",
    ["compra KO", "¿debería comprar KO?", "¿A qué precio compré KO?", "¿Cuándo vendí KO y cuánto IRPF pago?"],
)
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "account_trades"
