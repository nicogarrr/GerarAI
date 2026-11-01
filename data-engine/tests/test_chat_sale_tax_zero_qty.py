"""«¿Cuánto IRPF pagaría si vendo 0 UBER?» con 30 UBER guardadas.

Respondía «Pides vender 0 acciones de UBER, pero tienes 30», como si el
problema fuera que tienes de más. Ahora dice claramente que la cantidad
tiene que ser mayor que 0 (y sigue sin calcular nada).
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
        raise AssertionError("la simulación de IRPF no llama al LLM")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        comp = Company(ticker="UBER", name="Uber Technologies", exchange="NYSE", company_type="platform",
                       valuation_model="unassigned")
        session.add(comp)
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


@pytest.mark.parametrize("question", [
    "¿Cuánto IRPF pagaría si vendo 0 UBER?",
    "¿cuánto pagaría de impuestos si vendo 0 acciones de UBER?",
])
def test_vender_cero_pide_una_cantidad_mayor_que_cero(db, question):
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "portfolio_sale_tax"
    assert "mayor que 0" in resp.answer
    assert "pero tienes" not in resp.answer
    assert "tienes 30 acciones de UBER" in resp.answer
    assert "Confirma la cantidad" in resp.answer
    assert "IRPF estimado" not in resp.answer


def test_vender_de_mas_sigue_diciendo_cuantas_tienes(db):
    resp = _ask(db, "¿Cuánto IRPF pagaría si vendo 50 UBER?")
    assert "Pides vender 50 acciones de UBER, pero tienes 30" in resp.answer
