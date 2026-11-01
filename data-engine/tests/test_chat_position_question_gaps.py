"""Preguntas por TU posición en un ticker que iban al volcado de la empresa.

«¿Cuánto dinero tengo en UBER?», «¿Tengo UBER?», «¿Qué porcentaje de mi
cartera es UBER?», «¿Cuál es mi precio medio en ASTS?» o «¿Cuánto he
invertido en MSFT?» respondían «Todavía no tengo hechos financieros fiables
almacenados para UBER; ingiere sus fuentes primarias…» con la posición
guardada delante.
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
    ("¿Cuánto dinero tengo en UBER?", "Tu posición guardada en UBER: 30 acciones"),
    ("¿Tengo UBER?", "Tu posición guardada en UBER: 30 acciones"),
    ("¿Qué porcentaje de mi cartera es UBER?", "47,1 %"),
    ("¿Cuál es mi precio medio en ASTS?", "coste medio 12,00 €"),
])
def test_pregunta_por_tu_posicion_responde_con_ella(db, question, fragment):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "portfolio_position"
    assert fragment in resp.answer


def test_tengo_ticker_sin_posicion_lo_dice(db):
    resp = _ask(db, "¿Tengo NVDA?")
    assert resp.llm_trace["path"] == "portfolio_position"
    assert "NVDA" in resp.answer


@pytest.mark.parametrize(("question", "fragment"), [
    ("¿Cuánto he invertido en MSFT?", "coste 1.500,00 €"),
    ("¿Cuánto tengo invertido?", "coste 4.600,00 €"),
])
def test_cuanto_he_invertido_es_el_coste(db, question, fragment):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert fragment in resp.answer


def test_tengo_que_vender_no_es_pregunta_de_posicion(db):
    resp = _ask(db, "¿Tengo que vender UBER?")
    assert (resp.llm_trace or {}).get("path") != "portfolio_position"


@pytest.mark.parametrize("question", ["¿Tengo UBER en la watchlist?", "¿Tengo alguna alerta en UBER?"])
def test_tengo_con_otra_cosa_no_es_la_posicion(db, question):
    resp = _ask(db, question)
    assert (resp.llm_trace or {}).get("path") != "portfolio_position"
