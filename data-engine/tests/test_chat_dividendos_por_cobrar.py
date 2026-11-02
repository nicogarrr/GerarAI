"""Chat: «¿qué dividendos voy a cobrar?» lista los dividendos declarados aún sin pagar.

Antes estas preguntas daban el total de dividendos declarados del año («… en
2026»), que mezcla lo ya cobrado con lo que falta, sin fechas de pago; en inglés
«what dividends will I receive?» iba al modelo general. Solo lectura, de la
tabla guardada y solo con las posiciones del tenant.
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
        raise AssertionError("los dividendos por cobrar no deben pasar por el LLM")


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


@pytest.mark.parametrize("question", [
    "¿Qué dividendos voy a cobrar?",
    "¿Cuándo cobro el próximo dividendo?",
    "mis próximos dividendos",
    "¿Cuánto me van a pagar de dividendos?",
])
def test_pending_dividends(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_upcoming_dividends"
    assert resp.llm_trace["provider_calls"] == 0
    ko_pay, msft_pay = TODAY + timedelta(days=12), TODAY + timedelta(days=39)
    assert (f"- KO: 10,20 USD (0,51 USD × 20); ex-dividendo el {fecha_es(TODAY - timedelta(days=3))}, "
            f"pago el {fecha_es(ko_pay)}") in resp.answer
    assert (f"- MSFT: 4,55 USD (0,91 USD × 5); ex-dividendo el {fecha_es(TODAY + timedelta(days=18))}, "
            f"pago el {fecha_es(msft_pay)}") in resp.answer
    # Por fecha de pago; lo ya pagado no sale.
    assert resp.answer.index("- KO:") < resp.answer.index("- MSFT:")
    assert "0,83" not in resp.answer
    assert "Total: 14,75 USD." in resp.answer
    assert "Sin dividendo declarado pendiente: UBER." in resp.answer
    assert "AAPL" not in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Qué dividendos voy a cobrar?")
    assert "- AAPL: 2,60 USD (0,26 USD × 10)" in resp.answer
    assert "MSFT" not in resp.answer and "KO" not in resp.answer


def test_no_positions():
    db = _db()
    db.info["tenant_id"] = 3
    resp = _ask(db, "¿Qué dividendos voy a cobrar?")
    assert resp.answer.startswith("No tienes posiciones abiertas")


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        db = _db()
        db.info["language"] = "en"
        for question in ("What dividends will I receive?", "upcoming dividends", "When do I get my next dividend?"):
            resp = _ask(db, question)
            assert resp.llm_trace["path"] == "account_upcoming_dividends", question
            assert resp.answer.startswith("Declared dividends you still have to collect")
            assert "- MSFT: 4.55 USD (0.91 USD × 5)" in resp.answer
            assert "Total: 14.75 USD." in resp.answer
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("question", [
    "¿Cuántos dividendos he cobrado este año?",
    "¿Cuándo paga MSFT el próximo dividendo?",
    "¿Cuánto IRPF pagué en 2025?",
])
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "account_upcoming_dividends"
