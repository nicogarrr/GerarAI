"""SequentialFallbackProvider: reintento transitorio único y cadena OpenCode free -> Gemini."""
import asyncio
from functools import wraps

from app.llm.chat_provider import (
    GEMINI_MODEL,
    GROQ_MODEL,
    SequentialFallbackProvider,
    create_background_llm_provider,
)
from app.llm.contracts import LLMRequest, LLMResponse, Message, Usage
from app.llm.errors import (
    ProviderHTTPError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTransportError,
)


def run_async(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapped


def response(text="ok", *, model="primary", provider="opencode-go"):
    return LLMResponse(Message("assistant", text), Usage(), model, provider, finish_reason="stop")


class Fake:
    name = "fake"
    supported_capabilities = frozenset({"text", "structured_output"})
    model_router = None

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes) or [response()]
        self.calls = []

    async def complete(self, request):
        self.calls.append(request)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


REQ = LLMRequest([Message("user", "extrae")], task="main_financial_analysis")


@run_async
async def test_primary_ok_never_touches_backup():
    p, b = Fake(), Fake()
    out = await SequentialFallbackProvider(p, b, retry_pause=0).complete(REQ)
    assert out.provider == "opencode-go" and not b.calls


@run_async
async def test_transient_timeout_retries_primary_once():
    p = Fake(ProviderTransportError("opencode-go", "timeout", 1), response())
    b = Fake()
    out = await SequentialFallbackProvider(p, b, retry_pause=0).complete(REQ)
    assert out.provider == "opencode-go"
    assert len(p.calls) == 2 and not b.calls


@run_async
async def test_repeated_timeout_falls_to_groq_with_pinned_model():
    p = Fake(ProviderTransportError("opencode-go", "timeout", 1))
    b = Fake(response(model=GROQ_MODEL, provider="groq"))
    out = await SequentialFallbackProvider(p, b, retry_pause=0).complete(REQ)
    assert out.provider == "groq"
    assert len(p.calls) == 2  # reintento único, no uno por proveedor
    assert b.calls[0].model == GROQ_MODEL


@run_async
async def test_non_transient_goes_straight_to_fallback():
    p = Fake(ProviderHTTPError("opencode-go", 500))
    b = Fake(response(provider="groq"))
    out = await SequentialFallbackProvider(p, b, retry_pause=0).complete(REQ)
    assert out.provider == "groq"
    assert len(p.calls) == 1  # sin reintento: no era transitorio


@run_async
async def test_groq_failure_falls_to_gemini():
    p = Fake(ProviderHTTPError("opencode-go", 429))
    b = Fake(ProviderHTTPError("groq", 429))
    g = Fake(response(model=GEMINI_MODEL, provider="gemini"))
    out = await SequentialFallbackProvider(p, b, g, retry_pause=0).complete(REQ)
    assert out.provider == "gemini" and g.calls[0].model == GEMINI_MODEL


@run_async
async def test_all_providers_failed_raises_last():
    p = Fake(ProviderHTTPError("opencode-go", 500))
    b = Fake(ProviderHTTPError("groq", 429))
    try:
        await SequentialFallbackProvider(p, b, retry_pause=0).complete(REQ)
    except ProviderHTTPError as exc:
        assert exc.status_code == 429
    else:
        raise AssertionError("debía relanzar el último error")


@run_async
async def test_request_error_propagates_without_fallback():
    p = Fake(ProviderRequestError("petición mal construida"))
    b = Fake()
    try:
        await SequentialFallbackProvider(p, b, retry_pause=0).complete(REQ)
    except ProviderRequestError:
        pass
    else:
        raise AssertionError("debía propagarse")
    assert not b.calls


@run_async
async def test_empty_reply_is_transient():
    p = Fake(ProviderResponseError("provider returned an empty assistant message"), response())
    out = await SequentialFallbackProvider(p, None, retry_pause=0).complete(REQ)
    assert out.provider == "opencode-go" and len(p.calls) == 2


def test_factory_returns_primary_when_no_backup_configured():
    from app.core.config import Settings

    settings = Settings(
        llm_enabled=True,
        llm_provider="opencode-go",
        opencode_go_api_key="sk-test",
        opencode_free_chat_fallback_enabled=False,
        gemini_chat_fallback_enabled=False,
    )
    provider = create_background_llm_provider(settings)
    assert provider.name == "opencode-go"


def test_factory_wraps_with_backups_when_configured():
    from app.core.config import Settings

    settings = Settings(
        llm_enabled=True,
        llm_provider="opencode-go",
        opencode_go_api_key="sk-test",
        gemini_chat_fallback_enabled=False,
    )
    provider = create_background_llm_provider(settings)
    assert isinstance(provider, SequentialFallbackProvider)
    assert provider.backup is not None and provider.backup.name == "opencode-free"
    assert provider.backup2 is None



def test_background_backups_use_long_call_budgets_not_chat_budgets():
    """Un lote de extraccion son ~6k tokens in / 3k out: con los 12-18 s del
    chat los respaldos caian en read timeout y el job moria («La extracción
    tardó demasiado», prod 18 oct 2026). El chat conserva sus presupuestos
    cortos via los defaults."""
    from app.core.config import Settings
    from app.llm.chat_provider import create_chat_llm_provider

    settings = Settings(
        llm_enabled=True,
        llm_provider="opencode-go",
        opencode_go_api_key="sk-test",
        gemini_chat_fallback_enabled=True,
        gemini_api_key="gm-test",
        gemini_free_plan_confirmed=True,
    )
    provider = create_background_llm_provider(settings)
    assert provider.backup._timeout.read == 60.0  # noqa: SLF001
    assert provider.backup._total_timeout_seconds == 75.0  # noqa: SLF001
    assert provider.backup2._timeout.read == 90.0  # noqa: SLF001
    assert provider.backup2._total_timeout_seconds == 110.0  # noqa: SLF001

    chat = create_chat_llm_provider(settings)
    assert chat.backup._timeout.read == 15.0  # noqa: SLF001
    gemini_chat = chat.extra_backups[0][0]
    assert gemini_chat._timeout.read == 15.0  # noqa: SLF001
