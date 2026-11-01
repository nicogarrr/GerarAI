"""Chat en inglés: el resumen de cartera («How is my portfolio doing?») y su caja.

Con el inglés elegido salía siempre en español («Tu cartera guardada tiene…»).
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, CashBalance, Company, Position
from app.services.chat_service import ChatService


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _session(language: str):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = 1
    session.info["language"] = language
    for ticker, qty, cost, value in (("UBER", 30, 1500, 2400), ("MSFT", 1, 240, 1800)):
        comp = Company(ticker=ticker, name=f"{ticker} Inc", exchange="NYSE", company_type="platform",
                       valuation_model="unassigned")
        session.add(comp)
        session.flush()
        session.add(Position(
            tenant_id=1, company_id=comp.id, quantity=Decimal(qty), average_cost=Decimal(cost) / qty,
            market_value=Decimal(value), market_value_base=Decimal(value), cost_basis_base=Decimal(cost),
            currency="EUR", base_currency="EUR", as_of=date(2026, 10, 30),
        ))
    session.add(CashBalance(tenant_id=1, currency="EUR", balance=Decimal("1250.50"), as_of=date(2026, 10, 30)))
    session.commit()
    return session


def _ask(db, question):
    return asyncio.run(ChatService().answer(db, question, "portfolio", None))


def test_overview_in_english():
    db = _session("en")
    resp = _ask(db, "How is my portfolio doing?")
    assert resp.llm_trace["path"] == "portfolio_overview"
    assert resp.answer == (
        "Your saved portfolio has 2 open positions, total value 4,200.00 €, as of Oct 30, 2026:\n"
        "- UBER: 30 shares, average cost 50.00 €, value 2,400 € (57.1%)\n"
        "- MSFT: 1 share, average cost 240.00 €, value 1,800 € (42.9%)\n\n"
        "Also: cash 1,250.50 €; net worth 5,450.50 €."
    )


def test_overview_in_spanish_is_unchanged():
    db = _session("es")
    resp = _ask(db, "¿Cómo va mi cartera?")
    assert resp.answer == (
        "Tu cartera guardada tiene 2 posiciones abiertas, valor total 4.200,00 €, con datos a 30 oct 2026:\n"
        "- UBER: 30 acciones, coste medio 50,00 €, valor 2.400 € (57,1 %)\n"
        "- MSFT: 1 acciones, coste medio 240,00 €, valor 1.800 € (42,9 %)\n\n"
        "Además: caja 1.250,50 €; patrimonio neto 5.450,50 €."
    )
