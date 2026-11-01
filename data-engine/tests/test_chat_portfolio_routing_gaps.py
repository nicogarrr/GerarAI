"""Preguntas de cartera que caían fuera de la ruta determinista.

«¿Cuál es mi mayor posición?» entraba en el ranking pero sin métrica
(no decía «valor» ni «peso») y acababa en «No tengo fuentes verificadas…».
«¿Cuánto pierdo con ASTS?» iba al volcado de la empresa («ingiere sus
fuentes primarias…») en vez de a la rentabilidad de tu posición.
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
        session.commit()
        yield session


def _ask(db, question):
    return asyncio.run(ChatService().answer(db, question, "portfolio", None))


@pytest.mark.parametrize(("question", "ticker"), [
    ("¿Cuál es mi mayor posición?", "UBER"),
    ("¿Cuál es mi menor posición?", "ASTS"),
])
def test_mayor_o_menor_posicion_responde_por_valor(db, question, ticker):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "portfolio_ranking"
    assert resp.llm_trace["provider_calls"] == 0
    assert f"es {ticker}" in resp.answer


@pytest.mark.parametrize(("question", "ticker"), [
    ("¿Qué posición tiene el coste medio más alto?", "MSFT"),
    ("¿Qué posición tiene el precio medio más bajo?", "ASTS"),
])
def test_coste_medio_mas_alto_o_bajo(db, question, ticker):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "portfolio_ranking"
    assert f"es {ticker}" in resp.answer


@pytest.mark.parametrize(("question", "fragment"), [
    ("¿Cuánto pierdo con ASTS?", "-25 %"),
    ("¿Cuánto gano con UBER?", "+26,32 %"),
    ("¿Cuánto llevo ganado con UBER?", "+26,32 %"),
    ("¿Voy ganando o perdiendo con ASTS?", "-25 %"),
])
def test_cuanto_gano_o_pierdo_con_ticker_es_su_rentabilidad(db, question, fragment):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert fragment in resp.answer


def test_cuanto_pierdo_si_cae_no_es_la_rentabilidad_guardada(db):
    """Un escenario («si cae un 20 %») no se contesta con la cifra de hoy."""
    resp = _ask(db, "¿Cuánto pierdo con ASTS si cae un 20 %?")
    assert (resp.llm_trace or {}).get("path") != "portfolio_performance"
