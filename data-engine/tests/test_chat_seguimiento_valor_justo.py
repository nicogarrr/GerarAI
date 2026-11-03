"""Chat: «¿Y su valor justo?» sigue hablando de la empresa del hilo.

Prueba real 2026-11-02 (cerebro-real-1, B04): tras preguntar por Microsoft,
«¿Y su valor justo?» no recogía la empresa del hilo (solo lo hacían las
preguntas con pista de empresa o de métrica) y acababa en «No puedo
responderte con fuentes». El valor justo, el precio objetivo o la
valoración también son preguntas de empresa.
"""

import asyncio

import pytest

from app.core.i18n import reset_language_scope, set_language_scope
from app.schemas.api import ChatTurn
from app.services.chat_service import ChatService
from tests.cerebro_seed import seeded_session


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise RuntimeError("sin modelo en el test")


def _ask(question, history, lang="es"):
    token = set_language_scope(lang)
    try:
        db = seeded_session()
        db.info["language"] = lang
        return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "portfolio", None, history=history))
    finally:
        reset_language_scope(token)


@pytest.mark.parametrize(
    ("question", "lang"),
    [
        ("¿Y su valor justo?", "es"),
        ("¿Y el precio objetivo?", "es"),
        ("¿Cuál es su valoración?", "es"),
        ("And its fair value?", "en"),
    ],
)
def test_valuation_follow_up_uses_the_company_of_the_thread(question, lang):
    history = [
        ChatTurn(role="user", content="Cuéntame de UBER"),
        ChatTurn(role="assistant", content="UBER cotiza a 69,00 USD."),
    ]
    response = _ask(question, history, lang)
    assert "UBER" in response.answer
    assert "No puedo responderte con fuentes" not in response.answer


def test_without_a_company_in_the_thread_nothing_is_invented():
    history = [ChatTurn(role="user", content="hola"), ChatTurn(role="assistant", content="¡Hola!")]
    response = _ask("¿Y su valor justo?", history)
    assert "UBER" not in response.answer
