"""Chat: «calendario de dividendos» / «dividend calendar» da tus dividendos por cobrar.

Antes estas preguntas caían al modelo general, que sin fuentes contestaba
«No puedo responderte con fuentes ahora mismo». Ahora van a la misma
respuesta que «¿qué dividendos voy a cobrar?»: lo declarado y aún sin pagar de
tus posiciones, con fechas. Solo lectura y solo del tenant.
"""

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.local_date import local_today
from app.models.entities import Base, Company, DividendRecord, Position
from app.services.chat_service import ChatService
from app.services.display_es import fecha_es

TODAY = local_today()


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el calendario de dividendos no debe pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    ids = {}
    for ticker in ("MSFT", "KO", "UBER", "AAPL"):
        company = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="platform",
                          valuation_model="unassigned", currency="USD")
        db.add(company)
        db.flush()
        ids[ticker] = company.id
    holdings = {1: (("MSFT", "5"), ("KO", "20"), ("UBER", "30")), 2: (("AAPL", "10"),)}
    dividends = {
        1: (("MSFT", 18, 39, "0.91"),   # ex y pago futuros
            ("KO", -3, 12, "0.51"),     # ex pasado, pago futuro: aún por cobrar
            ("KO", -95, -80, "0.51"),   # ya pagado: no sale
            ("MSFT", -60, -40, "0.83")),
        2: (("AAPL", 7, 10, "0.26"),),
    }
    for tenant in (1, 2):
        db.info["tenant_id"] = tenant
        for ticker, qty in holdings[tenant]:
            db.add(Position(tenant_id=tenant, company_id=ids[ticker], quantity=Decimal(qty),
                            average_cost=Decimal("10"), currency="USD", as_of=TODAY))
        for ticker, ex, pay, amount in dividends[tenant]:
            db.add(DividendRecord(tenant_id=tenant, company_id=ids[ticker], ex_date=TODAY + timedelta(days=ex),
                                  pay_date=TODAY + timedelta(days=pay), amount=Decimal(amount), currency="USD",
                                  source="fmp"))
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["calendario de dividendos", "¿Cómo va mi calendario de dividendos?",
                                      "calendario de mis dividendos"])
def test_dividend_calendar(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_upcoming_dividends"
    assert (f"- KO: 10,20 USD (0,51 USD × 20); ex-dividendo el {fecha_es(TODAY - timedelta(days=3))}, "
            f"pago el {fecha_es(TODAY + timedelta(days=12))}") in resp.answer
    assert "Total: 14,75 USD." in resp.answer
    assert "AAPL" not in resp.answer


@pytest.mark.parametrize("question", ["dividend calendar", "show me my dividend calendar"])
def test_dividend_calendar_english(question, monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        db = _db()
        db.info["language"] = "en"
        resp = _ask(db, question)
    finally:
        get_settings.cache_clear()
    assert resp.llm_trace["path"] == "account_upcoming_dividends"
    assert "KO" in resp.answer and "MSFT" in resp.answer and "AAPL" not in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "calendario de dividendos")
    assert resp.llm_trace["path"] == "account_upcoming_dividends"
    assert "AAPL" in resp.answer
    for leak in ("KO", "MSFT", "UBER"):
        assert leak not in resp.answer


def test_ticker_calendar_stays_on_the_company():
    resp = _ask(_db(), "calendario de dividendos de KO")
    assert resp.llm_trace.get("path") != "account_upcoming_dividends"
