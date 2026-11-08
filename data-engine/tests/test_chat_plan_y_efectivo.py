"""«¿Cuánto efectivo tengo y cuánto debería aportar según mi plan?» contesta las dos partes (benchmark Cerebro, 2026-11-08).

Antes la pregunta doble iba al plan y el efectivo se perdía: «Tu plan guardado
marca una aportación de 600,00 € al mes…» sin los 3.200 € que tienes. Ahora
la respuesta lleva el saldo guardado y luego el plan. Una pregunta de plan sin
«efectivo» no cambia, ni «flujo de caja».
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, CashBalance, InvestmentPlan, Portfolio
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("esta respuesta no pasa por el modelo")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = 1
    session.add(Portfolio(tenant_id=1, name="Principal", base_currency="EUR"))
    session.add(
        InvestmentPlan(
            tenant_id=1,
            monthly_contribution=Decimal("600"),
            monthly_contribution_currency="EUR",
            start_date=date(2026, 6, 1),
            horizon_years=10,
            target_allocations=[],
        )
    )
    session.add(CashBalance(tenant_id=1, currency="EUR", balance=Decimal("3200"), as_of=date(2026, 11, 7)))
    session.commit()
    yield session
    session.close()


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "portfolio", None))  # type: ignore[arg-type]


def test_cash_and_plan_question_gets_both(db):
    resp = _ask(db, "¿Cuánto efectivo tengo y cuánto debería aportar este mes según mi plan?")
    assert "3.200,00" in resp.answer
    assert "600,00" in resp.answer
    assert resp.answer.index("3.200,00") < resp.answer.index("600,00")


def test_plan_question_without_cash_is_unchanged(db):
    resp = _ask(db, "¿Cómo va mi plan de inversión?")
    assert "600,00" in resp.answer and "3.200" not in resp.answer


def test_cash_flow_is_not_your_cash(db):
    assert "3.200" not in _ask(db, "¿Mi plan de inversión tiene en cuenta el flujo de caja?").answer
