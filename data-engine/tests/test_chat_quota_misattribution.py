"""El aviso «límite de uso» solo cuando OpenCode Go agota de verdad su cuota.

Prueba real del chat (2026-11-02, DeepSeek v4.1 Flash por OpenCode Go):
«¿Debería vender Santander?» contestaba «El modelo configurado ha llegado a
su límite de uso». Era falso: Go respondió, el validador rechazó esa
respuesta y el respaldo gratuito devolvió 429. El 429 del ÚLTIMO respaldo
se leía como cuota agotada del modelo configurado.
"""

from __future__ import annotations

import asyncio

import pytest

from app.llm.chat_provider import (
    GO_SUBSCRIPTION_PROVIDER,
    OPENCODE_FREE_PROVIDER,
    ChatFallbackProvider,
    is_quota_exhausted,
    reset_quota_cooldowns,
)
from app.llm.contracts import LLMRequest, Message
from app.llm.errors import ProviderHTTPError, ProviderResponseError


class _Fake:
    supported_capabilities = frozenset({"text", "structured_output"})
    model_router = None

    def __init__(self, value, *, name, delay=0.0):
        self.name = name
        self.value = value
        self.delay = delay

    async def complete(self, request):
        await asyncio.sleep(self.delay)
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


@pytest.fixture(autouse=True)
def _clean_cooldowns():
    reset_quota_cooldowns()
    yield
    reset_quota_cooldowns()


def _fail(primary_error, *, primary_delay=0.0) -> BaseException:
    primary = _Fake(primary_error, name=GO_SUBSCRIPTION_PROVIDER, delay=primary_delay)
    backup = _Fake(ProviderHTTPError(OPENCODE_FREE_PROVIDER, 429), name=OPENCODE_FREE_PROVIDER)
    chat = ChatFallbackProvider(primary, backup, total=1.0, delay=0.2, backup_model="deepseek-v4.1-flash-free")
    request = LLMRequest([Message("user", "¿Debería vender Santander?")], task="chat")
    with pytest.raises(Exception) as caught:
        asyncio.run(chat.complete(request))
    return caught.value


def test_go_rechazado_y_respaldo_429_no_es_cuota_agotada():
    exc = _fail(ProviderResponseError("Candidate rejected: Ungrounded general output"))
    assert not is_quota_exhausted(exc)


def test_go_sin_respuesta_a_tiempo_y_respaldo_429_no_es_cuota_agotada():
    exc = _fail(ProviderResponseError("nunca llega"), primary_delay=5.0)
    assert not is_quota_exhausted(exc)


def test_go_429_y_respaldo_429_si_es_cuota_agotada():
    exc = _fail(ProviderHTTPError(GO_SUBSCRIPTION_PROVIDER, 429))
    assert is_quota_exhausted(exc)

