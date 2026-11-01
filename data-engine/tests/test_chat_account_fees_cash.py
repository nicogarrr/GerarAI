"""Chat: comisiones pagadas y efectivo de la cuenta.

Antes «¿cuántas comisiones he pagado?» iba a la ruta general y «¿cuánto
efectivo tengo?» también; ahora salen de tus operaciones guardadas
(transactions.fees y filas de comisión) y de tus saldos (cash_balances).
Solo lectura y solo tus datos.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, CashBalance, Company, Transaction
from app.services import brain_account_tools
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("comisiones y efectivo no deben pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    cos = {}
    for ticker in ("UBER", "KO", "AAPL"):
        c = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="platform",
                    valuation_model="unassigned", currency="USD")
        db.add(c)
        db.flush()
        cos[ticker] = c

    def tx(tenant, ticker, day, action, qty, price, fees="0"):
        db.add(Transaction(tenant_id=tenant, company_id=cos[ticker].id, trade_date=day, action=action,
                           quantity=Decimal(qty), price=Decimal(price), fees=Decimal(fees), currency="USD"))

    db.info["tenant_id"] = 1
    tx(1, "UBER", date(2025, 3, 1), "buy", 40, "50", "1")
    tx(1, "UBER", date(2026, 6, 1), "sell", 10, "80", "1.5")
    tx(1, "KO", date(2026, 2, 5), "buy", 20, "60", "2")
    tx(1, "KO", date(2026, 7, 1), "fee", 1, "-3")
    db.add(CashBalance(tenant_id=1, currency="EUR", balance=Decimal("1234.50"), as_of=date(2026, 10, 30)))
    db.add(CashBalance(tenant_id=1, currency="USD", balance=Decimal("-200"), as_of=date(2026, 10, 29)))
    db.commit()
    db.info["tenant_id"] = 2
    tx(2, "AAPL", date(2026, 5, 4), "buy", 100, "170", "99")
    db.add(CashBalance(tenant_id=2, currency="EUR", balance=Decimal("777777"), as_of=date(2026, 10, 30)))
    db.commit()
    db.info["tenant_id"] = 1
    return db


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 10, 30))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Cuántas comisiones he pagado?", "mis comisiones", "¿cuánto he pagado en comisiones?"])
def test_fees_total(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_fees"
    assert resp.answer.startswith("Comisiones de compraventa en total: 4,50 USD (3 operaciones).")
    assert "Más: UBER 2,50 USD, KO 2,00 USD." in resp.answer
    assert "Otros cargos del bróker (filas de comisión): 3,00 USD." in resp.answer
    assert "99" not in resp.answer and "AAPL" not in resp.answer


def test_fees_this_year():
    resp = _ask(_db(), "¿Cuántas comisiones he pagado este año?")
    assert resp.answer.startswith("Comisiones de compraventa en 2026: 3,50 USD (2 operaciones).")


def test_fees_none():
    resp = _ask(_db(), "¿Cuántas comisiones pagué en 2020?")
    assert resp.answer == "No hay comisiones en 2020 en tus operaciones guardadas."


@pytest.mark.parametrize("question", ["¿Cuánto efectivo tengo?", "¿cuánta liquidez tengo?", "mi saldo de caja"])
def test_cash(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace["path"] == "account_cash"
    assert resp.answer.startswith("Tu efectivo guardado (a 30 oct 2026): 1.234,50 €, -200,00 USD.")
    assert "Un saldo negativo es deuda de margen." in resp.answer
    assert "777" not in resp.answer


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    fees = _ask(db, "¿Cuántas comisiones he pagado?")
    cash = _ask(db, "¿Cuánto efectivo tengo?")
    assert "99,00 USD" in fees.answer and "UBER" not in fees.answer and "4,50" not in fees.answer
    assert "777.777,00 €" in cash.answer and "1.234" not in cash.answer
    db.info["tenant_id"] = 3
    assert _ask(db, "¿Cuánto efectivo tengo?").answer.startswith("No tienes efectivo guardado.")
    assert _ask(db, "mis comisiones").answer == "No hay comisiones en total en tus operaciones guardadas."


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    assert _ask(db, "How much have I paid in fees?").answer.startswith(
        "Commissions on buys and sells in total: 4.50 USD (3 trades).")
    assert _ask(db, "How much cash do I have?").answer.startswith("Your saved cash (as of Oct 30, 2026): 1,234.50 €")


@pytest.mark.parametrize("question", [
    "¿Cuál es el flujo de caja libre de UBER?",
    "¿Cuánto efectivo tiene UBER?",
    "¿Qué comisión cobra el ETF?",
])
def test_company_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace.get("path") not in {"account_fees", "account_cash"}
