"""Chat «¿cuánto he ganado este año?»: el latente no mezcla posiciones sin cotización.

La línea «Latente» sumaba todas las posiciones abiertas con valor guardado,
incluidas las valoradas al precio de su última operación porque no tienen
cotización (auditoría A3: su plusvalía no está medida, cartera e impuestos la
dan como desconocida). Y las que no tenían valor quedaban fuera sin decirlo.
Ahora el latente es solo de las posiciones cotizadas y se nombran las demás.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Company, MarketPrice, Position, Transaction
from app.services import brain_account_tools
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("el resumen del año no debe pasar por el LLM")


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(brain_account_tools, "local_today", lambda: date(2026, 10, 30))
    monkeypatch.setattr(brain_account_tools, "_tax_data", lambda db, year: {"summary": {}, "realized": []})
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _db(with_unquoted=True):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    rows = [("UBER", "100", "150", True, True)]
    if with_unquoted:
        rows += [("NEWCO", "100", "100", False, True), ("GHOST", "100", "100", False, False)]
    for ticker, buy, mark, quoted, valued in rows:
        company = Company(ticker=ticker, name=ticker, exchange="NYSE", company_type="platform",
                          valuation_model="unassigned", currency="EUR")
        db.add(company)
        db.flush()
        db.add(Transaction(tenant_id=1, company_id=company.id, trade_date=date(2026, 10, 1), action="buy",
                           quantity=Decimal(10), price=Decimal(buy), fees=Decimal("0"), currency="EUR"))
        if quoted:
            db.add(MarketPrice(company_id=company.id, date=date(2026, 10, 29), open=Decimal(mark),
                               high=Decimal(mark), low=Decimal(mark), close=Decimal(mark)))
        value = Decimal(10) * Decimal(mark)
        cost = Decimal(10) * Decimal(buy)
        db.add(Position(tenant_id=1, company_id=company.id, quantity=Decimal(10), average_cost=Decimal(buy),
                        market_price=Decimal(mark), market_value=value, market_value_native=value,
                        market_value_base=value if valued else None, cost_basis_native=cost,
                        cost_basis_base=cost, currency="EUR", base_currency="EUR", as_of=date(2026, 10, 30),
                        source="postgres_ledger"))
    db.commit()
    return db


def _ask(db, question="¿Cuánto he ganado este año?"):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


def test_latent_only_counts_quoted_positions_and_names_the_rest():
    resp = _ask(_db())
    assert resp.llm_trace["path"] == "account_year_gains"
    assert "- Latente (lo que sigue abierto, no vendido): +500,00 € (+50,0 %) sobre un coste de 1.000,00 €" in resp.answer
    assert "Fuera del latente (sin cotización real o sin valor guardado): GHOST, NEWCO." in resp.answer


def test_all_quoted_unchanged():
    resp = _ask(_db(with_unquoted=False))
    assert "+500,00 € (+50,0 %) sobre un coste de 1.000,00 €" in resp.answer
    assert "Fuera del latente" not in resp.answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _db()
    db.info["language"] = "en"
    resp = _ask(db, "How much have I made this year?")
    assert "+500.00 € (+50.0%) on a cost of 1,000.00 €" in resp.answer
    assert "Left out of the unrealized figure (no real quote or no saved value): GHOST, NEWCO." in resp.answer
