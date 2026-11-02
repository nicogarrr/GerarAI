"""Chat «¿cuánto me han retenido?»: los dividendos en peniques (GBp) se suman en libras.

Los dividendos de Londres van en la divisa de la operación, a menudo «GBp»
(peniques). La respuesta de retenciones hacía ``.upper()`` sobre la divisa y
«GBp» pasaba a «GBP» sin dividir: un dividendo de 1.200 peniques (12 GBP) salía
como 1.200,00 GBP y se sumaba a los dividendos en libras de otras empresas. Mismo
fallo que las comisiones (#4235); ahora usa ``normalize_currency``.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, FXRate, Transaction
from app.services import brain_account_tools
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("la retención no debe pasar por el LLM")


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 10, 30))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    cos = {}
    for ticker, currency in (("TSCO.L", "GBp"), ("SHEL", "GBP")):
        company = Company(ticker=ticker, name=ticker, exchange="LSE", company_type="platform",
                          valuation_model="unassigned", currency=currency)
        db.add(company)
        db.flush()
        cos[ticker] = company

    def tx(ticker, action, amount, currency):
        db.add(Transaction(tenant_id=1, company_id=cos[ticker].id, trade_date=date(2026, 6, 1), action=action,
                           quantity=Decimal(1), price=Decimal(amount), fees=Decimal(0), currency=currency))

    tx("TSCO.L", "dividend", "1200", "GBp")  # 12 GBP
    tx("TSCO.L", "withholding", "120", "GBp")  # 1,20 GBP
    tx("SHEL", "dividend", "5", "GBP")
    day = date(2026, 1, 1)
    while day <= date(2026, 11, 1):
        db.add(FXRate(tenant_id=1, base_currency="EUR", quote_currency="GBP", rate=Decimal("0.85"),
                      rate_date=day, source="ecb"))
        day += timedelta(days=1)
    db.commit()
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


def test_pence_dividends_are_added_in_pounds():
    resp = _ask(_db(), "¿Cuánta retención me han aplicado en TSCO.L y SHEL en 2026?")
    assert resp.llm_trace["path"] == "account_withholding"
    assert "1.200" not in resp.answer and "1.205" not in resp.answer
    assert "1,20 GBP sobre 17,00 GBP brutos (7,1 %)" in resp.answer
    assert "- SHEL: 0,00 GBP sobre 5,00 GBP" in resp.answer
    assert "- TSCO.L: 1,20 GBP sobre 12,00 GBP (10,0 %)" in resp.answer


def test_pence_dividends_by_ticker():
    resp = _ask(_db(), "¿Cuánto me han retenido de TSCO.L?")
    assert resp.llm_trace["path"] == "account_withholding"
    assert "1,20 GBP sobre 12,00 GBP brutos (10,0 %)" in resp.answer
