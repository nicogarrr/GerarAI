"""«¿Qué porcentaje de mi patrimonio está en liquidez?» da el porcentaje (benchmark Cerebro, 2026-11-08).

Antes contestaba solo el saldo («Tu efectivo guardado: 3.200,00 €.») sin el
peso que se preguntaba. Ahora va al resumen de cartera, que suma caja y
posiciones, y dice qué parte del patrimonio es caja. «¿Cuánto efectivo
tengo?» sigue dando el saldo.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest

from app.models.entities import CashBalance
from app.services.chat_service import ChatService
from tests.test_chat_english_sale_tax import _session


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("esta respuesta no pasa por el modelo")


@pytest.fixture
def db():
    session = _session("es")
    session.add(CashBalance(tenant_id=1, currency="EUR", balance=Decimal("1000"), as_of=date(2026, 10, 30)))
    session.commit()
    yield session
    session.close()


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "portfolio", None))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "question",
    [
        "¿Qué porcentaje de mi patrimonio está en liquidez?",
        "¿Qué peso tiene el efectivo en mi cartera?",
    ],
)
def test_cash_share_question_gets_the_percentage(db, question):
    resp = _ask(db, question)
    # Posiciones 5.100 € + caja 1.000 € = 6.100 €; la caja es el 16,4 %.
    assert "patrimonio neto 6.100,00 €" in resp.answer
    assert "la caja es el 16,4 % del patrimonio" in resp.answer


def test_plain_cash_question_still_gives_the_balance(db):
    resp = _ask(db, "¿Cuánto efectivo tengo?")
    assert resp.llm_trace["path"] == "account_cash" and "1.000,00 €" in resp.answer
