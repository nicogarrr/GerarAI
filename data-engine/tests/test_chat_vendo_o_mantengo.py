"""Chat: «¿Vendo Uber o la mantengo?» es una consulta, no una orden.

Prueba real 2026-11-03 (cerebro-real-2): contestaba «No ejecuto órdenes:
GerarAI no compra ni vende en tu bróker». Igual que #4386 con «¿debería
vender X?»: preguntar entre dos opciones pide opinión con los datos. Una
orden de verdad («vende mis acciones de UBER», «compra 10 UBER») sigue sin
ejecutarse.
"""

import asyncio

import pytest

from app.core.i18n import reset_language_scope, set_language_scope
from app.services.chat_service import ChatService
from tests.cerebro_seed import seeded_session


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise RuntimeError("sin modelo en el test")


def _path(question, lang="es"):
    token = set_language_scope(lang)
    try:
        db = seeded_session()
        db.info["language"] = lang
        response = asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "portfolio", None))
        return (response.llm_trace or {}).get("path"), response.answer
    finally:
        reset_language_scope(token)


@pytest.mark.parametrize(
    ("question", "lang"),
    [
        ("¿Vendo Uber o la mantengo?", "es"),
        ("¿Mantengo UBER o vendo?", "es"),
        ("¿Compro más Uber o espero?", "es"),
        ("vendo uber o no", "es"),
        ("Sell or hold Uber?", "en"),
        ("Should I hold or sell UBER?", "en"),
    ],
)
def test_choice_between_options_is_not_an_order(question, lang):
    path, answer = _path(question, lang)
    assert path != "order_verb"
    assert "No ejecuto órdenes" not in answer and "I don't place orders" not in answer


@pytest.mark.parametrize(
    ("question", "lang"),
    [
        ("vende mis acciones de UBER", "es"),
        ("compra 10 UBER", "es"),
        ("sell my UBER shares", "en"),
    ],
)
def test_real_orders_are_still_not_executed(question, lang):
    path, _ = _path(question, lang)
    assert path == "order_verb"
