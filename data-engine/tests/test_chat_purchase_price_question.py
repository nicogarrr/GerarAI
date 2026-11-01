"""«¿A qué precio compré UBER?»: es tu coste de compra, no la cotización.

Antes «¿A qué precio compré UBER?» respondía con la cotización guardada,
«¿Cuál es mi precio de compra de MSFT?» contestaba «No ejecuto órdenes» (por
la palabra «compra») y «¿Cuánto pagué por mis ASTS?», «¿A qué precio medio
tengo UBER?» o «¿Cuánto me costaron las MSFT?» iban al volcado de la empresa
(«Todavía no tengo hechos financieros fiables…») con la posición guardada.
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
    ("¿A qué precio compré UBER?", "coste medio 63,33 €"),
    ("¿a cuánto compré las UBER?", "coste medio 63,33 €"),
    ("¿Cuál es mi precio de compra de MSFT?", "coste medio 300,00 €"),
    ("¿Cuánto pagué por mis ASTS?", "coste medio 12,00 €"),
    ("¿A qué precio medio tengo UBER?", "coste medio 63,33 €"),
    ("¿Cuánto me costaron las MSFT?", "coste medio 300,00 €"),
    ("¿Cuántas UBER tengo?", "30 acciones"),
])
def test_precio_de_compra_es_tu_coste(db, question, fragment):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "portfolio_position"
    assert fragment in resp.answer


def test_precio_de_compra_sin_posicion_lo_dice(db):
    resp = _ask(db, "¿A qué precio compré NVDA?")
    assert resp.llm_trace["path"] == "portfolio_position"
    assert "No tienes ninguna posición guardada en NVDA" in resp.answer


@pytest.mark.parametrize("question", ["Compra MSFT", "Vende mis UBER"])
def test_orden_de_compra_sigue_sin_ejecutarse(db, question):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "order_verb"


def test_precio_de_ticker_sigue_siendo_cotizacion(db):
    resp = _ask(db, "¿Qué precio tiene UBER?")
    assert resp.llm_trace["path"] == "company_quote"
