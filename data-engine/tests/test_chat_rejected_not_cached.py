"""Una respuesta de Go que el chat rechaza no se queda en la cache.

Prueba real del chat (2026-11-02): «¿Debería vender Santander?» → el
validador rechazó la respuesta de Go; al repetir la pregunta, la cache de
respuestas devolvía esa misma respuesta (0,3 s, sin llamar a Go) y el chat
volvía a fallar igual durante los 15 min de vida de la entrada.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app.llm.chat_provider import GO_SUBSCRIPTION_PROVIDER, ChatFallbackProvider, reset_quota_cooldowns
from app.llm.contracts import LLMRequest, LLMResponse, Message, Usage
from app.llm.errors import ProviderHTTPError


class _Cached:
    supported_capabilities = frozenset({"text", "structured_output"})
    model_router = None

    def __init__(self, text, *, name=GO_SUBSCRIPTION_PROVIDER):
        self.name = name
        self.text = text
        self.evicted: list[str] = []

    async def complete(self, request):
        resp = LLMResponse(Message("assistant", self.text), Usage(), "deepseek-v4.1-flash", self.name, finish_reason="stop")
        return replace(resp, cache_key="k-" + self.name)

    async def evict_cached(self, response):
        self.evicted.append(response.cache_key)


class _Down:
    supported_capabilities = frozenset({"text", "structured_output"})
    model_router = None
    name = "opencode-free"

    async def complete(self, request):
        raise ProviderHTTPError(self.name, 429)


@pytest.fixture(autouse=True)
def _clean():
    reset_quota_cooldowns()
    yield
    reset_quota_cooldowns()


def _reject(_resp):
    raise ValueError("Ungrounded general output")


def test_respuesta_rechazada_por_el_validador_sale_de_la_cache():
    primary = _Cached("Respuesta inventada con un 15 % sin fuente.")
    chat = ChatFallbackProvider(primary, _Down(), total=1.0, delay=0.5, validator=_reject)
    with pytest.raises(Exception):
        asyncio.run(chat.complete(LLMRequest([Message("user", "¿Debería vender Santander?")], task="chat")))
    assert primary.evicted == ["k-" + GO_SUBSCRIPTION_PROVIDER]


def test_respuesta_aceptada_se_queda_en_la_cache():
    primary = _Cached("Respuesta válida en español.")
    chat = ChatFallbackProvider(primary, _Down(), total=1.0, delay=0.5, validator=lambda r: None)
    out = asyncio.run(chat.complete(LLMRequest([Message("user", "hola")], task="chat")))
    assert out.text == "Respuesta válida en español." and primary.evicted == []
