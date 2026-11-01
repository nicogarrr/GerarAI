"""«¿Cuánto ganaría si vendo todo UBER?» con la posición guardada.

Respondía «No ejecuto órdenes: GerarAI no compra ni vende en tu bróker…»
(como si se hubiera pedido una orden) o el volcado de datos de la empresa.
Es la misma simulación que «¿cuánto IRPF pagaría si vendo…?»: ahora da la
ganancia (y el IRPF estimado) de esa venta hipotética.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *args, **kwargs):  # pragma: no cover - no debe llamarse
        raise AssertionError("la simulación de venta no llama al LLM")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        comp = Company(ticker="UBER", name="Uber Technologies", exchange="NYSE", company_type="platform",
                       valuation_model="unassigned")
        session.add(comp)
        session.add(Company(ticker="KO", name="Coca-Cola", exchange="NYSE", company_type="platform",
                            valuation_model="unassigned"))
        session.flush()
        session.add(Position(
            tenant_id=1, company_id=comp.id, quantity=Decimal("30"), average_cost=Decimal("75"),
            market_value=Decimal("2700"), market_value_native=Decimal("2700"), market_value_base=Decimal("2400"),
            cost_basis_native=Decimal("2250"), cost_basis_base=Decimal("1904.76"),
            currency="USD", base_currency="EUR", as_of=date(2026, 10, 27),
        ))
        session.commit()
        yield session


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize(("question", "fragment"), [
    ("¿Cuánto ganaría si vendo todo UBER?", "todas tus 30 acciones de UBER"),
    ("¿cuánto gano si vendo mis UBER?", "todas tus 30 acciones de UBER"),
    ("¿Qué ganancia tendría si vendo 10 UBER?", "10 de tus 30 acciones de UBER"),
    ("Si vendiera UBER hoy, ¿cuánto ganaría?", "todas tus 30 acciones de UBER"),
])
def test_ganancia_de_una_venta_hipotetica_usa_la_posicion(db, question, fragment):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert fragment in resp.answer
    assert "ganancia de" in resp.answer
    assert "No ejecuto órdenes" not in resp.answer


def test_venta_hipotetica_sin_posicion_lo_dice(db):
    resp = _ask(db, "¿Cuánto ganaría si vendo KO?")
    assert "No ejecuto órdenes" not in resp.answer
    assert "KO" in resp.answer


@pytest.mark.parametrize("question", ["vende mis UBER", "compra más UBER"])
def test_ordenes_siguen_sin_ejecutarse(db, question):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "order_verb"
