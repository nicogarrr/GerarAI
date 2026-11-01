"""Chat: «¿cuánta retención me han aplicado en MSFT?» con tus dividendos guardados.

Antes, una pregunta de retención con ticker acababa en el volcado de datos de la
empresa («Todavía no tengo hechos financieros fiables…»). Ahora suma la retención
en origen de tus cobros de esa empresa (mismo cálculo que Impuestos), por año.
Solo lectura y solo tus operaciones.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, FXRate, Transaction
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("la retención no debe pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    companies = {}
    for ticker in ("MSFT", "KO"):
        company = Company(ticker=ticker, name=ticker + " Inc", exchange="NYSE", company_type="platform",
                          valuation_model="unassigned", currency="USD")
        db.add(company)
        db.flush()
        companies[ticker] = company.id
    rows = {1: (("MSFT", date(2025, 3, 10), "dividend", "4.00"), ("MSFT", date(2025, 3, 10), "withholding", "0.60"),
                ("MSFT", date(2026, 3, 10), "dividend", "4.15"), ("MSFT", date(2026, 3, 10), "withholding", "0.62"),
                ("KO", date(2026, 4, 1), "dividend", "9.70"), ("KO", date(2026, 4, 1), "withholding", "1.46")),
            2: (("MSFT", date(2026, 3, 10), "dividend", "3.00"), ("MSFT", date(2026, 3, 10), "withholding", "0.45"))}
    for tenant, txs in rows.items():
        db.info["tenant_id"] = tenant
        for ticker, day, action, amount in txs:
            db.add(Transaction(tenant_id=tenant, company_id=companies[ticker], trade_date=day, action=action,
                               quantity=Decimal(1), price=Decimal(amount), fees=Decimal(0), currency="USD"))
        day = date(2024, 12, 1)
        while day <= date(2026, 11, 1):
            db.add(FXRate(tenant_id=tenant, base_currency="EUR", quote_currency="USD", rate=Decimal("0.9"),
                          rate_date=day, source="ecb"))
            day += timedelta(days=1)
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Cuánta retención me han aplicado en MSFT?",
                                      "¿Cuánto me han retenido de MSFT?", "retenciones de mis dividendos de MSFT"])
def test_withholding_one_ticker_all_years(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace.get("path") == "account_withholding"
    assert resp.answer.startswith("Retención en origen en tus dividendos de MSFT: 1,22 USD sobre 8,15 USD brutos (15,0 %).")
    assert "- 2026: 0,62 USD sobre 4,15 USD" in resp.answer
    assert "- 2025: 0,60 USD sobre 4,00 USD" in resp.answer
    assert "KO" not in resp.answer


def test_withholding_one_ticker_one_year():
    resp = _ask(_db(), "¿Cuánto me han retenido de KO este año?")
    assert resp.llm_trace.get("path") == "account_withholding"
    assert resp.answer.startswith("Retención en origen en tus dividendos de KO en 2026: 1,46 USD sobre 9,70 USD brutos (15,1 %).")
    assert "MSFT" not in resp.answer


def test_withholding_two_tickers():
    resp = _ask(_db(), "¿Cuánta retención me han aplicado en MSFT y KO en 2026?")
    assert resp.answer.startswith("Retención en origen en tus dividendos de KO, MSFT en 2026: 2,08 USD sobre 13,85 USD brutos (15,0 %).")
    assert "- KO: 1,46 USD sobre 9,70 USD (15,1 %)" in resp.answer and "- MSFT: 0,62 USD sobre 4,15 USD (14,9 %)" in resp.answer


def test_no_dividends_for_ticker():
    resp = _ask(_db(), "¿Cuánta retención me han aplicado en AAPL?")
    assert resp.answer.startswith("No tienes dividendos ni retenciones guardados de AAPL.")


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "¿Cuánta retención me han aplicado en MSFT?")
    assert resp.answer.startswith("Retención en origen en tus dividendos de MSFT: 0,45 USD sobre 3,00 USD brutos (15,0 %).")
    assert "0,62" not in resp.answer and "KO" not in resp.answer
    db.info["tenant_id"] = 3
    resp = _ask(db, "¿Cuánta retención me han aplicado en MSFT?")
    assert resp.answer.startswith("No tienes dividendos ni retenciones guardados de MSFT.")


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        db = _db()
        db.info["language"] = "en"
        resp = _ask(db, "How much withholding tax have I paid on MSFT?")
        assert resp.answer.startswith("Tax withheld at source on your MSFT dividends: 1.22 USD on 8.15 USD gross (15.0%).")
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("question", ["¿Qué retención aplica Estados Unidos a los dividendos?", "¿Qué retenciones me han hecho este año?",
                                      "¿Cuánto dividendo paga MSFT?", "¿Cómo va MSFT?"])
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace.get("path") != "account_withholding"
