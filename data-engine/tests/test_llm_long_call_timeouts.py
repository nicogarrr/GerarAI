"""Timeouts de llamadas largas al bridge OpenCode y presupuesto corto del chat.

Decision (2026-10-19): el bridge con reasoning=max tarda ~26 s o mas por
lote y un corte de cliente a los 30 s tiraba ~30 % de las peticiones
(BrokenPipe en el bridge). Las llamadas largas (extraccion de
documentos/principios, tesis, KPIs) pasan a 120 s por intento con 1
reintento y tope total de 250 s; el chat interactivo conserva su
presupuesto corto (45 s) y compite con reasoning reducido.
"""

from app.core.config import Settings
from app.llm.chat_provider import (
    ChatFallbackProvider,
    SequentialFallbackProvider,
    create_background_llm_provider,
    create_chat_llm_provider,
)
from app.llm.contracts import LLMRequest, Message
from app.llm.factory import create_llm_provider


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, opencode_go_api_key="k", **overrides)


def test_long_call_defaults_are_120s_one_retry_250s_total() -> None:
    settings = _settings()
    assert settings.llm_timeout_seconds == 120.0
    assert settings.llm_max_retries == 1
    assert settings.llm_total_timeout_seconds == 250.0


def test_primary_provider_uses_long_call_defaults() -> None:
    provider = create_llm_provider(_settings())
    assert provider._timeout.read == 120.0  # noqa: SLF001
    assert provider._max_retries == 1  # noqa: SLF001
    assert provider._total_timeout_seconds == 250.0  # noqa: SLF001


def test_background_primary_retries_only_via_sequential_fallback() -> None:
    # El reintento unico lo hace SequentialFallbackProvider; si el primario
    # ademas reintentara por dentro, un bridge caido costaria ~4 intentos de
    # 120 s por lote antes de llegar a Groq/Gemini.
    provider = create_background_llm_provider(
        _settings(
            groq_api_key="k",
            groq_chat_fallback_enabled=True,
            groq_free_plan_confirmed=True,
            groq_zdr_confirmed=True,
        )
    )
    assert isinstance(provider, SequentialFallbackProvider)
    assert provider.primary._max_retries == 0  # noqa: SLF001
    assert provider.primary._timeout.read == 120.0  # noqa: SLF001


def _chat_chain(**overrides) -> ChatFallbackProvider:
    settings = _settings(
        groq_api_key="k",
        groq_chat_fallback_enabled=True,
        groq_free_plan_confirmed=True,
        groq_zdr_confirmed=True,
        **overrides,
    )
    provider = create_chat_llm_provider(settings)
    assert isinstance(provider, ChatFallbackProvider)
    return provider


def test_chat_keeps_its_own_short_total_budget() -> None:
    chain = _chat_chain()
    assert chain.total == 20.0
    # Y el primario hereda el timeout largo por llamada individual: el tope
    # de la carrera es quien recorta el chat, no el cliente HTTP.
    assert chain.primary._timeout.read == 120.0  # noqa: SLF001


def test_chat_primary_makes_a_single_attempt_per_model() -> None:
    chain = _chat_chain()
    assert chain.primary._max_retries == 0  # noqa: SLF001


def test_chat_primary_uses_reduced_reasoning_by_default() -> None:
    chain = _chat_chain()
    assert chain.primary._reasoning_effort == "low"  # noqa: SLF001


def test_chat_reasoning_override_is_configurable() -> None:
    chain = _chat_chain(opencode_go_chat_reasoning_effort="max")
    assert chain.primary._reasoning_effort == "max"  # noqa: SLF001


def test_chat_reasoning_effort_reaches_the_payload() -> None:
    chain = _chat_chain()
    request = LLMRequest(messages=[Message("user", "hola")], task="chat")
    model = chain.primary.model_router.resolve(request)
    payload = chain.primary._build_payload(request, model)  # noqa: SLF001
    assert payload["reasoning_effort"] == "low"


def test_non_chat_primary_keeps_reasoning_max() -> None:
    provider = create_llm_provider(_settings())
    request = LLMRequest(messages=[Message("user", "extrae")], task="claim_extraction")
    model = provider.model_router.resolve(request)
    payload = provider._build_payload(request, model)  # noqa: SLF001
    assert payload["reasoning_effort"] == "max"
