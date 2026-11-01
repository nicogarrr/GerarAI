"""Sinónimos de posición y rentabilidad que caían en el volcado de la empresa.

«¿Cuántos títulos tengo de MSFT?», «¿Cuánto representa UBER en mi cartera?»,
«¿Cuánto me ha rentado UBER?» o «¿Qué beneficio tengo en UBER?» respondían
«Todavía no tengo hechos financieros fiables…» (o el beneficio neto de la
empresa) con la posición guardada.
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
    ("¿Cuántos títulos tengo de MSFT?", "5 acciones"),
    ("¿Cuántos títulos de ASTS tengo?", "100 acciones"),
    ("¿Cuánto representa UBER en mi cartera?", "30 acciones"),
])
def test_titulos_y_representa_van_a_la_posicion(db, question, fragment):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "portfolio_position"
    assert fragment in resp.answer


@pytest.mark.parametrize(("question", "fragment"), [
    ("¿Cuánto me ha rentado UBER?", "posición en UBER"),
    ("¿Qué beneficio tengo en UBER?", "posición en UBER"),
    ("¿Qué beneficio llevo con ASTS?", "posición en ASTS"),
])
def test_rentado_y_beneficio_propio_van_a_la_rentabilidad(db, question, fragment):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert fragment in resp.answer
