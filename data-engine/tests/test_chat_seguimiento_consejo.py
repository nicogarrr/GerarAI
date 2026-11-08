"""«¿Debería comprar más?» tras hablar de una empresa habla de esa empresa (benchmark Cerebro, 2026-11-08).

Antes el seguimiento de opinión sin nombre caía en la vía general, que no ve
la cartera ni las fuentes, y contestaba «No puedo responderte con fuentes
ahora mismo» o hablaba en abstracto. Ahora toma la empresa del hilo, igual que
«¿y su deuda?». Una orden sin opinión («Compra más») no se arrastra.
"""

import asyncio

import pytest

from app.schemas.api import ChatTurn
from app.services.chat_service import ChatService
from tests.test_chat_english_sale_tax import _session


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise RuntimeError("sin modelo en el test")


_HISTORY = [
    ChatTurn(role="user", content="¿Cómo va UBER?"),
    ChatTurn(role="assistant", content="UBER cotiza por encima de tu coste medio."),
]


@pytest.fixture
def db():
    session = _session("es")
    yield session
    session.close()


def _ask(db, question, history=_HISTORY):
    return asyncio.run(
        ChatService(provider=_NoLLM()).answer(db, question, "portfolio", None, history=history)
    )  # type: ignore[arg-type]


@pytest.mark.parametrize("question", ["¿Debería comprar más?", "¿Me conviene vender?", "¿Qué opinas?"])
def test_advice_follow_up_uses_the_company_from_the_thread(db, question):
    resp = _ask(db, question)
    assert resp.llm_trace.get("path") != "general"
    assert "UBER" in resp.answer


def test_bare_order_is_not_carried(db):
    assert "UBER" not in _ask(db, "Compra más").answer


def test_without_thread_nothing_is_carried(db):
    assert "UBER" not in _ask(db, "¿Debería comprar más?", history=None).answer
