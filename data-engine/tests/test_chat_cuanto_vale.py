"""«¿Cuánto vale X?» pregunta por la empresa, no por tu posición (benchmark Cerebro, 2026-11-08).

Antes «¿Cuánto vale POOL?» con POOL en cartera contestaba «Tu posición guardada
en POOL: 8 acciones… valor 1.516,88 €» y «¿Qué escenarios tiene la valoración de
META?» decía «No tengo escenarios de valoración» aunque el motor los tiene.
Ahora sin posesivo va al motor de valoración (bajista/base/alcista y precio
usado); «¿cuánto valen mis X?» sigue siendo tu posición.
"""

import asyncio

import pytest

from app.services.chat_service import ChatService
from tests.test_chat_english_sale_tax import _session


@pytest.fixture
def db():
    session = _session("es")
    yield session
    session.close()


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("esta ruta no llama al modelo")


def _path(db, question):
    resp = asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "portfolio", None))  # type: ignore[arg-type]
    return resp.llm_trace.get("path"), resp.answer


@pytest.mark.parametrize(
    "question",
    [
        "¿Cuánto vale UBER?",
        "¿Cuánto vale ASTS según su valoración?",
        "¿Qué escenarios tiene la valoración de UBER?",
    ],
)
def test_company_value_questions_go_to_the_valuation_engine(db, question):
    path, answer = _path(db, question)
    assert path == "engine_valuation", (path, answer)
    assert "Tu posición guardada" not in answer


@pytest.mark.parametrize(
    "question",
    [
        "¿Cuánto valen mis UBER?",
        "¿Cuántas acciones tengo de UBER?",
        "¿Cuánto vale mi posición en UBER?",
    ],
)
def test_possessive_questions_stay_on_your_position(db, question):
    path, _answer = _path(db, question)
    assert path == "portfolio_position"


def test_price_today_and_worth_it_are_not_the_engine(db):
    assert _path(db, "¿Cuánto vale UBER hoy?")[0] != "engine_valuation"
    assert _path(db, "¿Cuánto vale la pena invertir al mes?")[0] != "engine_valuation"
