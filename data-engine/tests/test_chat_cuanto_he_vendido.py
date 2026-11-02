"""Chat: «how much did I sell this year?» / «¿cuánto he vendido este año?» con tus ventas.

Antes solo «¿qué he vendido este año?» / «what did I sell this year?» iban a las
ventas del año; «how much did I sell…» caía al modelo general («I can't answer
with sources…») y «¿cuánto he vendido…?» igual. Ahora van a la misma respuesta
(el FIFO del informe fiscal con tus operaciones). Solo lectura y solo del tenant.
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
        raise AssertionError("las ventas no deben pasar por el LLM")


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 11, 2))


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    for tenant, ticker in ((1, "KO"), (2, "TSLA")):
        company = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="consumer",
                          valuation_model="unassigned", currency="EUR")
        db.add(company)
        db.flush()
        db.info["tenant_id"] = tenant
        portfolio = Portfolio(tenant_id=tenant, name="Principal", base_currency="EUR", is_default=True)
        db.add(portfolio)
        db.flush()
        for day, action, price in ((date(2025, 5, 2), "buy", "10"), (date(2026, 3, 2), "sell", "15")):
            db.add(Transaction(tenant_id=tenant, portfolio_id=portfolio.id, company_id=company.id, trade_date=day,
                               action=action, quantity=Decimal("4"), price=Decimal(price), currency="EUR"))
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Qué he vendido este año?", "¿Cuánto he vendido este año?",
                                      "how much did I sell this year?", "How much have I sold this year?"])
def test_how_much_did_i_sell(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_sales"
    assert resp.llm_trace["provider_calls"] == 0
    assert "KO" in resp.answer and "TSLA" not in resp.answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    try:
        resp = _ask(db, "How much did I sell this year?")
    finally:
        get_settings.cache_clear()
    assert resp.llm_trace["path"] == "account_sales"
    assert "KO" in resp.answer and "TSLA" not in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "how much did I sell this year?")
    assert resp.llm_trace["path"] == "account_sales"
    assert "TSLA" in resp.answer and "KO" not in resp.answer
