"""«¿Qué tal va mi UBER?», «¿Gano o pierdo con UBER?», «¿Cuánto me ha costado
MSFT?» y «¿A cuánto está UBER?» iban al volcado de la empresa («Todavía no
tengo hechos financieros fiables…») en vez de a tu rentabilidad, tu coste o
la cotización guardada.
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


@pytest.mark.parametrize(("question", "fragment"), [
    ("¿Qué tal va mi UBER?", "+26,32 %"),
    ("¿Qué tal van mis ASTS?", "-25 %"),
    ("¿Gano o pierdo con UBER?", "+26,32 %"),
    ("¿Cuánto me ha costado MSFT?", "coste 1.500,00 €"),
])
def test_tu_rentabilidad_o_coste_de_un_ticker(db, question, fragment):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "portfolio_performance"
    assert fragment in resp.answer


@pytest.mark.parametrize("question", ["¿A cuánto está UBER?", "¿a cuánto están las MSFT?"])
def test_a_cuanto_esta_es_la_cotizacion(db, question):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "company_quote"


def test_si_es_escenario_no_es_la_cifra_guardada(db):
    resp = _ask(db, "¿Gano o pierdo con UBER si baja un 10 %?")
    assert (resp.llm_trace or {}).get("path") != "portfolio_performance"
