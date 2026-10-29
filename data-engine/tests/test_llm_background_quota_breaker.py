"""Breaker de cuota 429 para flujos de fondo (jev_fallback y cia.).

Reproduccion del hallazgo de prod (worker-default, ~21:43-21:48 UTC): con el
cupo semanal de opencode-go agotado, cada `classify_free` hacia max_retries+1
intentos con backoff (0,75 s no recupera un cupo SEMANAL), logueaba un 429
por intento, y el siguiente item del lote volvia a sondear el proveedor
agotado: minutos de 429 repetidos. Con el breaker, el primer 429 "weekly
exhausted" hace UN solo intento y las llamadas dentro del cooldown fallan
rapido sin abrir conexion; al expirar, la siguiente llamada es una sonda
real (mismo patron que el breaker de origen 502).
"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.llm import base as llm_base
from app.llm.base import LLMProvider
from app.llm.contracts import LLMRequest, Message
from app.llm.errors import ProviderHTTPError


class _Router:
    def resolve(self, request):
        return "deepseek-v1.1-flash"


class _StubProvider(LLMProvider):
    """Proveedor de fondo (sin interactive_quota_breaker) sin red."""

    name = "opencode-go"
    supported_capabilities = frozenset({"text"})

    def __init__(self, body: str, status: int = 429):
        super().__init__(model_router=_Router(), max_retries=2)
        self._body = body
        self._status = status
        self.calls = 0

    async def complete(self, request: LLMRequest):
        return await self._post_json(
            "https://opencode.test/v1/chat/completions",
            headers={},
            payload={"model": "deepseek-v1.1-flash"},
        )

    async def _send(self, url, *, headers, payload):
        self.calls += 1
        return httpx.Response(self._status, text=self._body)


@pytest.fixture(autouse=True)
def _clear_breakers():
    # getattr: sin el fix el dict no existe y el test debe FALLAR, no dar error.
    breaker = getattr(llm_base, "_free_quota_breaker", None)
    if breaker is not None:
        breaker.clear()
    yield
    if breaker is not None:
        breaker.clear()


def _request() -> LLMRequest:
    return LLMRequest(messages=(Message("user", "hola"),), task="jev_fallback")


def test_quota_429_single_attempt_then_breaker_fails_fast():
    provider = _StubProvider("weekly exhausted")
    with pytest.raises(ProviderHTTPError) as excinfo:
        asyncio.run(provider.complete(_request()))
    assert excinfo.value.status_code == 429
    # Sin reintentos: un cupo semanal no vuelve en 0,75 s. Antes: 3 intentos.
    assert provider.calls == 1
    # Dentro del cooldown la siguiente llamada ni siquiera abre conexion.
    with pytest.raises(ProviderHTTPError) as excinfo2:
        asyncio.run(provider.complete(_request()))
    assert excinfo2.value.status_code == 429
    assert provider.calls == 1


def test_breaker_expires_and_probes_again():
    provider = _StubProvider("insufficient_quota")
    with pytest.raises(ProviderHTTPError):
        asyncio.run(provider.complete(_request()))
    assert provider.calls == 1
    # Cooldown expirado: la siguiente llamada es una sonda real.
    key = ("opencode-go", "deepseek-v1.1-flash")
    getattr(llm_base, "_free_quota_breaker")[key] = time.monotonic() - 1
    with pytest.raises(ProviderHTTPError):
        asyncio.run(provider.complete(_request()))
    assert provider.calls == 2


def test_plain_429_rate_limit_keeps_retries_and_sets_no_breaker():
    provider = _StubProvider("rate limit: too many requests, slow down")
    with pytest.raises(ProviderHTTPError):
        asyncio.run(provider.complete(_request()))
    # Rate limit puntual: se conservan los reintentos con backoff...
    assert provider.calls == 1 + 2  # max_retries=2
    # ...y NO se abre el breaker: la siguiente llamada vuelve a intentarlo.
    assert getattr(llm_base, '_free_quota_breaker', {}) == {}
    with pytest.raises(ProviderHTTPError):
        asyncio.run(provider.complete(_request()))
    assert provider.calls == 2 * (1 + 2)
