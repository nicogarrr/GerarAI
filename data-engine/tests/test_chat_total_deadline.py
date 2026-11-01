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


def response(text="válida", *, model="m", provider="p", finish="stop"):
    return LLMResponse(Message("assistant", text), Usage(), model, provider, finish_reason=finish)


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


@run_async
async def test_free_and_gemini_backup_payloads_keep_their_contracts():
    """La pata free fija el modelo deepseek free con effort low, y Gemini 3.x
    (que razona) eleva max_tokens=600 al minimo de razonamiento oculto en vez
    de truncar la respuesta visible."""
    from app.core.config import Settings
    from app.llm.chat_provider import create_chat_llm_provider

    settings = Settings(_env_file=None, llm_enabled=True, llm_provider="opencode-go",
                        opencode_go_api_key="fake", gemini_api_key="fake",
                        gemini_chat_fallback_enabled=True, gemini_free_plan_confirmed=True)
    provider = create_chat_llm_provider(settings)
    assert isinstance(provider, ChatFallbackProvider)
    request = LLMRequest([Message("user", "hola")], task="chat", max_tokens=600)
    free_payload = provider.backup._build_payload(request, "deepseek-v4.1-flash-free")
    assert free_payload["model"] == "deepseek-v4.1-flash-free"
    assert free_payload["reasoning_effort"] == "low"
    gemini_payload = provider.extra_backups[0][0]._build_payload(request, GEMINI_MODEL)
    assert gemini_payload["max_tokens"] >= 1024


@run_async
async def test_length_finish_reason_falls_through_to_gemini():
    """Un respaldo truncado (finish_reason=length) no se acepta: cae al siguiente."""
    primary = Fake(ProviderHTTPError("opencode-go", 429))
    groq = Fake(response(model=GROQ_MODEL, provider="groq", finish="length"), name="groq")
    gemini = Fake(response(model=GEMINI_MODEL, provider="gemini"), name="gemini")
    provider = ChatFallbackProvider(primary, groq, total=1, delay=.05, backup2=gemini)
    out = await provider.complete(chat_request())
    assert out.provider == "gemini"


def _general_baseline():
    from app.schemas import ChatResponse
    return ChatResponse(answer="baseline", sections=[], sources=[])


@run_async
async def test_real_general_flow_accepts_clean_groq_spanish():
    """Flujo general real (prompt chat_general, max_tokens=600): la prosa
    limpia en castellano del respaldo Groq se ACEPTA (fontaneria bien)."""
    from app.services.chat_synthesis_service import ChatSynthesisService

    clean = ("El margen operativo es la parte de los ingresos que queda tras "
             "pagar los costes de operar el negocio. Sirve para comparar la "
             "eficiencia de empresas de un mismo sector.")
    primary = Fake(ProviderHTTPError("opencode-go", 429))
    groq = Fake(response(clean, model=GROQ_MODEL, provider="groq"), name="groq")
    provider = ChatFallbackProvider(primary, groq, total=2, delay=.05)
    result = await ChatSynthesisService(provider).synthesize_general(
        question="qué es el margen operativo", baseline=_general_baseline())
    assert result.model == GROQ_MODEL
    assert "margen operativo" in result.answer


@run_async
async def test_real_general_flow_rejects_cjk_leak_and_uses_gemini():
    """La firma conocida de gpt-oss (fuga CJK) se rechaza y cae a Gemini."""
    from app.services.chat_synthesis_service import ChatSynthesisService

    leaked = ("El margen operativo es la parte de los ingresos que queda tras "
              "pagar los costes del negocio。Mide la eficiencia.")
    clean = ("El margen operativo es la parte de los ingresos que queda tras "
             "pagar los costes de operar el negocio.")
    primary = Fake(ProviderHTTPError("opencode-go", 429))
    groq = Fake(response(leaked, model=GROQ_MODEL, provider="groq"), name="groq")
    gemini = Fake(response(clean, model=GEMINI_MODEL, provider="gemini"), name="gemini")
    provider = ChatFallbackProvider(primary, groq, total=2, delay=.05, backup2=gemini)
    result = await ChatSynthesisService(provider).synthesize_general(
        question="qué es el margen operativo", baseline=_general_baseline())
    assert result.model == GEMINI_MODEL


class FlakyFake(Fake):
    """Fallos en cola por (modelo): cada llamada consume el siguiente."""

    def __init__(self, failures, **kwargs):
        super().__init__(**kwargs)
        self.failures = failures

    async def complete(self, request):
        self.calls.append(request)
        queue = self.failures.get(request.model, [])
        if queue:
            raise queue.pop(0)
        return response(model=request.model, provider=self.name)


@run_async
async def test_gemini_503_retried_once_then_success():
    primary = Fake(ProviderHTTPError("opencode-go", 429))
    groq = Fake(ProviderHTTPError("groq", 429), name="groq")
    gemini = FlakyFake({GEMINI_MODEL: [ProviderHTTPError("gemini", 503)]}, name="gemini")
    provider = ChatFallbackProvider(primary, groq, total=2, delay=.05, backup2=gemini)
    out = await provider.complete(chat_request())
    assert out.provider == "gemini"
    assert [c.model for c in gemini.calls] == [GEMINI_MODEL, GEMINI_MODEL]


@run_async
async def test_gemini_503_persistent_falls_to_next_model():
    primary = Fake(ProviderHTTPError("opencode-go", 429))
    groq = Fake(ProviderHTTPError("groq", 429), name="groq")
    gemini = FlakyFake(
        {GEMINI_MODEL: [ProviderHTTPError("gemini", 503), ProviderHTTPError("gemini", 503)]},
        name="gemini",
    )
    provider = ChatFallbackProvider(primary, groq, total=2, delay=.05, backup2=gemini)
    out = await provider.complete(chat_request())
    assert out.model == "gemini-3.8-flash"
    assert [c.model for c in gemini.calls] == [GEMINI_MODEL, GEMINI_MODEL, "gemini-3.8-flash"]


@run_async
async def test_deadline_cancels_the_provider_call_instead_of_leaving_it_running(monkeypatch):
    monkeypatch.setattr(interactive_deadline, "get_settings",
                        lambda: SimpleNamespace(chat_total_timeout_seconds=.2))
    provider = Fake(delay=5)

    @bounded_chat
    async def ask():
        return await complete_with_deadline(provider, chat_request(), source="test")

    with pytest.raises(TimeoutError):
        await ask()
    await asyncio.sleep(.1)
    assert provider.calls and provider.cancelled  # no hidden call keeps running


@run_async
async def test_cancelling_the_waiter_cancels_the_provider_call():
    provider = Fake(delay=5)
    waiter = asyncio.ensure_future(complete_with_deadline(provider, chat_request(), source="test"))
    await asyncio.sleep(.05)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await asyncio.sleep(.1)
    assert provider.cancelled


@run_async
async def test_a_finished_provider_call_is_not_cancelled_by_the_fix():
    provider = Fake(delay=0)
    result = await complete_with_deadline(provider, chat_request(), source="test")
    assert result is not None and not provider.cancelled


@run_async
async def test_deadline_expiry_detected_inside_is_still_timeout(monkeypatch):
    # Carrera vista en CI de main (c78fcec3): si el plazo vence y lo detecta
    # antes el código interno (remaining_seconds/complete_with_deadline) que el
    # wait_for externo, salía ProviderTransportError en vez de TimeoutError y
    # answer() no aplicaba su fallback rotulado. Se fuerza ese orden bloqueando
    # el loop hasta pasado el plazo: el resultado debe ser siempre TimeoutError.
    monkeypatch.setattr(interactive_deadline, "get_settings",
                        lambda: SimpleNamespace(chat_total_timeout_seconds=.05))

    @bounded_chat
    async def ask():
        time.sleep(.1)  # bloqueante a propósito: el timer externo no llega a correr
        return interactive_deadline.remaining_seconds()

    with pytest.raises(TimeoutError):
        await ask()


@run_async
async def test_provider_transport_timeout_from_a_real_provider_is_not_rewritten(monkeypatch):
    # Solo el vencimiento del plazo total se normaliza: un fallo de transporte
    # de un proveedor concreto conserva su tipo.
    monkeypatch.setattr(interactive_deadline, "get_settings",
                        lambda: SimpleNamespace(chat_total_timeout_seconds=5))

    @bounded_chat
    async def ask():
        raise ProviderTransportError("groq", "timeout", 2)

    with pytest.raises(ProviderTransportError):
        await ask()
