"""«¿Cuál es el coste medio de mis UBER?»: tu coste, no el volcado de la empresa.

Antes «el coste medio de mis UBER», «el precio medio de mis ASTS» o «el
precio medio de compra de mis MSFT» iban al volcado de datos de la empresa
(«Todavía no tengo hechos financieros fiables…»); solo «mi coste medio»
llegaba a la posición guardada.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position
from app.services.chat_service import ChatService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        for ticker, qty, cost, value in (("UBER", 30, 1900, 2400), ("ASTS", 100, 1200, 900), ("MSFT", 5, 1500, 1800)):
            comp = Company(ticker=ticker, name=f"{ticker} Inc", exchange="NYSE", company_type="platform",
                           valuation_model="unassigned")
            session.add(comp)
            session.flush()
            session.add(Position(
                tenant_id=1, company_id=comp.id, quantity=Decimal(qty), average_cost=Decimal(cost) / qty,
                market_value=Decimal(value), market_value_base=Decimal(value), cost_basis_base=Decimal(cost),
                currency="EUR", base_currency="EUR", as_of=date(2026, 10, 30),
            ))
        session.add(Company(ticker="NVDA", name="NVIDIA", exchange="NASDAQ", company_type="platform",
                            valuation_model="unassigned"))
        session.commit()
        yield session


def _ask(db, question):
    return asyncio.run(ChatService().answer(db, question, "portfolio", None))


@pytest.mark.parametrize(("question", "fragment"), [
    ("¿Cuál es el coste medio de mis UBER?", "coste medio 63,33 €"),
    ("¿Cuál es el precio medio de mis ASTS?", "coste medio 12,00 €"),
    ("precio medio de compra de mis MSFT", "coste medio 300,00 €"),
    ("¿Qué coste medio tienen mis UBER?", "coste medio 63,33 €"),
])
def test_coste_medio_de_mis_acciones_es_tu_posicion(db, question, fragment):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "portfolio_position"
    assert fragment in resp.answer
