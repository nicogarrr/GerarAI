"""Chat «¿cuántas comisiones he pagado?»: una operación en peniques (GBp) se suma en libras.

Las comisiones de una operación van en la divisa de la operación: en Londres
(«GBp») son peniques, como el precio. El informe fiscal ya las divide entre
100 (``_minor_divisor``); el chat hacía ``.upper()`` y «GBp» pasaba a «GBP»:
500 peniques (5 £) salían como 500,00 GBP y se sumaban a las comisiones en
libras de otras operaciones.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, Transaction
from app.services import brain_account_tools
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("las comisiones no deben pasar por el LLM")


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

    def tx(ticker, day, action, qty, price, fees, currency):
        db.add(Transaction(tenant_id=1, company_id=cos[ticker].id, trade_date=day, action=action,
                           quantity=Decimal(qty), price=Decimal(price), fees=Decimal(fees), currency=currency))

    tx("TSCO.L", date(2026, 3, 2), "buy", 100, "300", "500", "GBp")  # 500 peniques = 5 £
    tx("SHEL", date(2026, 4, 2), "buy", 10, "25", "2", "GBP")
    tx("TSCO.L", date(2026, 5, 2), "fee", 1, "-300", "0", "GBp")  # 3 £
    db.commit()
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


def test_pence_fees_are_added_in_pounds():
    resp = _ask(_db(), "¿Cuántas comisiones he pagado este año?")
    assert resp.llm_trace.get("path") == "account_fees"
    assert "Comisiones de compraventa en 2026: 7,00 GBP (2 operaciones)." in resp.answer
    assert "Más: TSCO.L 5,00 GBP, SHEL 2,00 GBP." in resp.answer
    assert "Otros cargos del bróker (filas de comisión): 3,00 GBP." in resp.answer
    assert "500,00" not in resp.answer and "300,00" not in resp.answer
