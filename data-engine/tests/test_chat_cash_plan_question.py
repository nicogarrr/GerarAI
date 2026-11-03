"""Una pregunta de plan que menciona la caja no se contesta con el saldo.

Prueba real del chat (2026-11-02): «Tengo 30 años, … y 2.500 € en efectivo.
Mi objetivo es jubilarme a los 55 … ¿Qué cambiarías de mi cartera y por qué,
paso a paso?» contestaba solo «Tu efectivo guardado (a 30 oct 2026):
2.500,00 €.». «¿Cuánto efectivo tengo?» sigue dando el saldo.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, CashBalance
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise RuntimeError("sin LLM en este test")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = 1
    session.add(CashBalance(tenant_id=1, currency="EUR", balance=Decimal("2500"), as_of=date(2026, 10, 30)))
    session.commit()
    yield session
    session.close()


def _path(db, q):
    r = asyncio.run(ChatService(provider=_NoLLM()).answer(db, q, "portfolio", None))
    return (r.llm_trace or {}).get("path"), r.answer


@pytest.mark.parametrize(
    "question",
    [
        "Tengo 30 años y 2.500 € en efectivo. Mi objetivo es jubilarme a los 55; ¿qué cambiarías de mi cartera y por qué, paso a paso?",
        "Con mi efectivo, ¿qué estrategia me recomiendas?",
    ],
)
def test_plan_con_efectivo_no_es_el_saldo(db, question):
    path, _ = _path(db, question)
    assert path != "account_cash"


def test_cuanto_efectivo_sigue_dando_el_saldo(db):
    path, answer = _path(db, "¿Cuánto efectivo tengo?")
    assert path == "account_cash" and "2.500,00" in answer
