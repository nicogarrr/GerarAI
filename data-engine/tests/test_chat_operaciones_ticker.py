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


@pytest.mark.parametrize("question", ["mis operaciones de KO", "¿Qué operaciones he hecho con KO?"])
def test_ticker_trades(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") == "account_trades"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.splitlines() == [
        "Tus compras y ventas guardadas de KO (la más reciente primero):",
        "- 5 oct 2026: compra de 10 KO a 60,50 USD.",
        "- 1 jun 2025: venta de 2 KO a 58,00 USD.",
    ]


@pytest.mark.parametrize("question", ["¿Cuándo compré KO?", "¿cuándo he comprado KO?", "mis compras de KO"])
def test_ticker_buys_only(question):
    """«¿cuándo compré KO?» lista solo las compras (antes mezclaba la venta de 2025)."""
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") == "account_trades"
    assert resp.answer.splitlines() == [
        "Tus compras guardadas de KO (la más reciente primero):",
        "- 5 oct 2026: compra de 10 KO a 60,50 USD.",
    ]


@pytest.mark.parametrize("question", ["¿cuándo vendí KO?", "mis ventas de KO"])
def test_ticker_sells_only(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") == "account_trades"
    assert resp.answer.splitlines() == [
        "Tus ventas guardadas de KO (la más reciente primero):",
        "- 1 jun 2025: venta de 2 KO a 58,00 USD.",
    ]


def test_ticker_buys_only_without_sells_or_buys():
    assert _ask(_db(), "¿cuándo vendí ITX?").answer == "No tienes ventas guardadas de ITX."
    assert _ask(_db(), "¿Cuándo compré MSFT?").answer == "No tienes compras guardadas de MSFT."


def test_ticker_without_trades():
    resp = _ask(_db(), "mis operaciones de MSFT")
    assert (resp.llm_trace or {}).get("path") == "account_trades"
    assert resp.answer == "No tienes compras ni ventas guardadas de MSFT."


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuándo compré KO?")
    assert "999" in resp.answer
    assert "60,50" not in resp.answer


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("my KO trades", [
            "Your saved buys and sells of KO (most recent first):",
            "- Oct 5, 2026: bought 10 KO at 60.50 USD.",
            "- Jun 1, 2025: sold 2 KO at 58.00 USD.",
        ]),
        ("When did I buy KO?", ["Your saved buys of KO (most recent first):", "- Oct 5, 2026: bought 10 KO at 60.50 USD."]),
        ("When did I sell KO?", ["Your saved sells of KO (most recent first):", "- Jun 1, 2025: sold 2 KO at 58.00 USD."]),
    ],
)
def test_english(monkeypatch, question, expected):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, question)
    finally:
        get_settings.cache_clear()
    assert (resp.llm_trace or {}).get("path") == "account_trades"
    assert resp.answer.splitlines() == expected


@pytest.mark.parametrize(
    "question",
    ["compra KO", "¿debería comprar KO?", "¿A qué precio compré KO?", "¿Cuándo vendí KO y cuánto IRPF pago?"],
)
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "account_trades"


@pytest.mark.parametrize(
    ("question", "head"),
    [
        ("¿Cuántas veces he comprado KO?", "Tienes 1 compra de KO guardada (la más reciente primero):"),
        ("¿cuántas compras de KO he hecho?", "Tienes 1 compra de KO guardada (la más reciente primero):"),
        ("¿cuántas veces vendí KO?", "Tienes 1 venta de KO guardada (la más reciente primero):"),
        ("¿cuántas operaciones de KO tengo?", "Tienes 1 compra y 1 venta de KO guardadas (la más reciente primero):"),
    ],
)
def test_ticker_count(question, head):
    """«¿cuántas veces he comprado KO?» daba los datos de la empresa; ahora el recuento y la lista."""
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") == "account_trades"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer.splitlines()[0] == head


def test_ticker_count_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "How many times did I buy KO?")
    finally:
        get_settings.cache_clear()
    assert resp.answer.splitlines() == [
        "You have 1 buy of KO saved (most recent first):",
        "- Oct 5, 2026: bought 10 KO at 60.50 USD.",
    ]


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("¿Cuál fue mi primera compra?", "Tu primera compra guardada: 12 sept 2026, 3 ITX a 45,20 USD."),
        ("¿cuál fue mi primera operación?", "Tu primera venta guardada: 1 jun 2025, 2 KO a 58,00 USD."),
        ("¿cuál fue mi primera venta?", "Tu primera venta guardada: 1 jun 2025, 2 KO a 58,00 USD."),
        ("¿Cuándo compré KO por primera vez?", "Tu primera compra guardada de KO: 5 oct 2026, 10 KO a 60,50 USD."),
    ],
)
def test_first_trade(question, answer):
    """«¿cuál fue mi primera compra?» iba al modelo general; «¿cuándo compré KO por
    primera vez?» listaba de la más reciente a la más antigua. Ahora, la más antigua."""
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") == "account_trades"
    assert resp.llm_trace["provider_calls"] == 0
    assert resp.answer == answer


def test_first_trade_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "What was my first purchase?")
    finally:
        get_settings.cache_clear()
    assert resp.answer == "Your first saved purchase: Sep 12, 2026, 3 ITX at 45.20 USD."
