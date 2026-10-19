"""Plazo total del chat y cadena 429 -> Groq -> Gemini con proveedores fake."""
import asyncio
import time
from functools import wraps
from types import SimpleNamespace

import pytest

from app.llm import interactive_deadline
from app.llm.chat_provider import (
    GEMINI_MODEL,
    GROQ_MODEL,
    ChatFallbackProvider,
    _note_failure,
    reset_quota_cooldowns,
)
from app.llm.contracts import LLMRequest, LLMResponse, Message, Usage
from app.llm.errors import ProviderHTTPError, ProviderTransportError
from app.llm.interactive_deadline import bounded_chat, complete_with_deadline


def run_async(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapped


def response(text="válida", *, model="m", provider="p"):
    return LLMResponse(Message("assistant", text), Usage(), model, provider, finish_reason="stop")


class Fake:
    """Proveedor falso: valor fijo, excepcion o comportamiento por modelo."""

    def __init__(self, value=None, delay=0, name="fake", by_model=None):
        self.name = name
        self.supported_capabilities = frozenset({"text", "structured_output"})
        self.model_router = None
        self.value = value if value is not None else response(provider=name)
        self.delay = delay
        self.by_model = by_model or {}
        self.calls = []
        self.cancelled = False

    async def complete(self, request):
        self.calls.append(request)
        try:
            await asyncio.sleep(self.delay)
            value = self.by_model.get(request.model, self.value)
            if isinstance(value, Exception):
                raise value
            return value
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def chat_request():
    return LLMRequest([Message("user", "hola")], task="chat")


@pytest.fixture(autouse=True)
def _clean_cooldowns():
    reset_quota_cooldowns()
    yield
    reset_quota_cooldowns()


@run_async
async def test_429_primary_and_groq_reaches_gemini():
    primary = Fake(ProviderHTTPError("opencode-go", 429))
    groq = Fake(ProviderHTTPError("groq", 429), name="groq")
    gemini = Fake(response(model=GEMINI_MODEL, provider="gemini"), name="gemini")
    provider = ChatFallbackProvider(primary, groq, total=1, delay=.05, backup2=gemini)
    out = await provider.complete(chat_request())
    assert out.provider == "gemini"
    assert groq.calls and groq.calls[0].model == GROQ_MODEL
    assert gemini.calls and gemini.calls[0].model == GEMINI_MODEL


@run_async
async def test_transport_error_primary_uses_groq():
    primary = Fake(ProviderTransportError("opencode-go", "read_timeout", 1))
    groq = Fake(response(model=GROQ_MODEL, provider="groq"), name="groq")
    provider = ChatFallbackProvider(primary, groq, total=1, delay=.05)
    out = await provider.complete(chat_request())
    assert out.provider == "groq"


@run_async
async def test_http_error_primary_uses_groq():
    primary = Fake(ProviderHTTPError("opencode-go", 500))
    groq = Fake(response(model=GROQ_MODEL, provider="groq"), name="groq")
    provider = ChatFallbackProvider(primary, groq, total=1, delay=.05)
    out = await provider.complete(chat_request())
    assert out.provider == "groq"


@run_async
async def test_gemini_first_model_429_second_model_answers():
    primary = Fake(ProviderHTTPError("opencode-go", 429))
    groq = Fake(ProviderHTTPError("groq", 429), name="groq")
    gemini = Fake(
        by_model={
            GEMINI_MODEL: ProviderHTTPError("gemini", 429),
            "gemini-3.8-flash": response(model="gemini-3.8-flash", provider="gemini"),
        },
        name="gemini",
    )
    provider = ChatFallbackProvider(primary, groq, total=1, delay=.05, backup2=gemini)
    out = await provider.complete(chat_request())
    assert out.model == "gemini-3.8-flash"
    assert [c.model for c in gemini.calls] == [GEMINI_MODEL, "gemini-3.8-flash"]


@run_async
async def test_total_deadline_bounds_hanging_providers():
    primary, groq, gemini = Fake(delay=5), Fake(delay=5), Fake(delay=5)
    provider = ChatFallbackProvider(primary, groq, total=.15, delay=.05, backup2=gemini)
    start = time.monotonic()
    with pytest.raises(ProviderTransportError):
        await provider.complete(chat_request())
    assert time.monotonic() - start < 1
    assert primary.cancelled


@run_async
async def test_cooled_members_raise_429_without_calls():
    primary = Fake(ProviderHTTPError("opencode-go", 429))
    groq = Fake(name="groq")
    gemini = Fake(name="gemini")
    _note_failure(groq, GROQ_MODEL, ProviderHTTPError("groq", 429))
    _note_failure(gemini, GEMINI_MODEL, ProviderHTTPError("gemini", 429))
    _note_failure(gemini, "gemini-3.8-flash", ProviderHTTPError("gemini", 429))
    provider = ChatFallbackProvider(primary, groq, total=1, delay=.05, backup2=gemini)
    with pytest.raises(ProviderHTTPError):
        await provider.complete(chat_request())
    # El primario se intento; los respaldos en enfriamiento no reciben llamadas.
    assert primary.calls and not groq.calls and not gemini.calls


@run_async
async def test_complete_with_deadline_preserves_provider_timeout():
    provider = Fake(TimeoutError("slow"))
    with pytest.raises(TimeoutError):
        await complete_with_deadline(provider, chat_request(), source="test")


@run_async
async def test_complete_with_deadline_bounds_guard(monkeypatch):
    monkeypatch.setattr(interactive_deadline, "get_settings",
                        lambda: SimpleNamespace(chat_total_timeout_seconds=.2))

    @bounded_chat
    async def ask():
        return await complete_with_deadline(Fake(delay=5), chat_request(), source="test")

    start = time.monotonic()
    with pytest.raises(TimeoutError):
        await ask()
    assert time.monotonic() - start < 1


@run_async
async def test_nested_deadline_is_not_restarted(monkeypatch):
    monkeypatch.setattr(interactive_deadline, "get_settings",
                        lambda: SimpleNamespace(chat_total_timeout_seconds=.3))

    @bounded_chat
    async def ask():
        await asyncio.sleep(.2)
        # Quedan ~0,1 s de presupuesto: un proveedor colgado 1 s no debe
        # disponer de otros 0,3 s completos.
        return await complete_with_deadline(Fake(delay=1), chat_request(), source="test")

    start = time.monotonic()
    with pytest.raises(TimeoutError):
        await ask()
    elapsed = time.monotonic() - start
    assert elapsed < .6


@run_async
async def test_cjk_retry_respects_total_deadline():
    primary = Fake(delay=5)
    groq = Fake(delay=5, name="groq")
    provider = ChatFallbackProvider(primary, groq, total=.15, delay=.05)
    start = time.monotonic()
    with pytest.raises(ProviderTransportError):
        await provider.complete_cjk_retry(chat_request())
    assert time.monotonic() - start < 1
    assert groq.cancelled
