"""Modo degradado y cascada de respaldo del LLM (revision GerarAI, hallazgo M1).

La cadena de plataforma es OpenCode Go -> OpenCode free (deepseek,
/zen/v1) -> Gemini. Los flags tienen modo ``auto`` (por defecto): cada
respaldo entra solo si su clave y las confirmaciones de plan gratuito
existen; sin clave se salta, nunca se finge.

Pruebas deterministas: el transporte HTTP es un ``httpx.MockTransport``, no
sale ninguna peticion real y no hace falta ninguna clave de verdad.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.chat_provider import (
    GEMINI_MODEL,
    SequentialFallbackProvider,
    create_background_llm_provider,
    create_chat_llm_provider,
)
from app.llm.contracts import LLMRequest, Message
from app.llm.errors import LLMError, ProviderDisabledError
from app.llm.factory import create_llm_provider
from app.llm.readiness import llm_configuration_issue
from app.schemas import ChatResponse, SynthesisSection
from app.services.chat_synthesis_service import SECTION_ORDER, ChatSynthesisService

REQ = LLMRequest([Message("user", "resume el ultimo 10-K")], task="main_financial_analysis")

GROQ_READY = {
    "groq_api_key": "gsk-sintetica",
    "groq_free_plan_confirmed": True,
    "groq_zdr_confirmed": True,
}
GEMINI_READY = {"gemini_api_key": "gm-sintetica", "gemini_free_plan_confirmed": True}


def _settings(**over) -> Settings:
    base: dict = {
        "llm_enabled": True,
        "llm_provider": "opencode-go",
        "opencode_go_api_key": "sk-sintetica",
    }
    base.update(over)
    return Settings(_env_file=None, **base)  # pyright: ignore[reportCallIssue]


def _completion(text: str, model: str) -> dict:
    return {
        "id": "cmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": text},
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class Upstreams:
    """Transporte falso: cada host responde lo que diga el test y se anota."""

    def __init__(self, status_by_host: dict[str, int]) -> None:
        self.status_by_host = status_by_host
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.calls.append(host)
        status = self.status_by_host.get(host, 599)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "caido"}})
        model = json.loads(request.content or b"{}").get("model", "?")
        return httpx.Response(200, json=_completion(f"respuesta de {host}", model))

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def _baseline() -> ChatResponse:
    sections = [
        SynthesisSection(
            key=key,
            body=f"baseline {key}",
            citations=["financial_fact:1"] if key in {"facts", "calculations"} else [],
        )
        for key in SECTION_ORDER
    ]
    return ChatResponse(
        answer="respuesta determinista",
        sections=sections,
        sources=[{"type": "financial_fact", "id": 1}],
    )


# --- Modo auto de los flags -------------------------------------------------


def test_auto_is_the_default_and_free_leg_follows_the_go_key() -> None:
    settings = _settings()
    assert settings.groq_chat_fallback_enabled is None  # auto
    assert settings.gemini_chat_fallback_enabled is None
    assert settings.opencode_free_chat_fallback_enabled is None
    assert settings.groq_chat_fallback_active is False
    assert settings.gemini_chat_fallback_active is False
    # Con clave Go la pata free entra en auto: es la misma clave, gasto 0.
    assert settings.opencode_free_chat_fallback_active is True
    provider = create_background_llm_provider(settings)
    assert isinstance(provider, SequentialFallbackProvider)
    assert provider.backup is not None and provider.backup.name == "opencode-free"
    # Apagada explicitamente y sin Gemini, queda el primario a secas.
    solo = _settings(opencode_free_chat_fallback_enabled=False)
    assert create_background_llm_provider(solo).name == "opencode-go"


@pytest.mark.parametrize("raw", ["auto", "AUTO", "", " auto "])
def test_auto_string_from_env_parses_to_auto(raw: str) -> None:
    settings = _settings(groq_chat_fallback_enabled=raw, gemini_chat_fallback_enabled=raw)
    assert settings.groq_chat_fallback_enabled is None
    assert settings.gemini_chat_fallback_enabled is None


def test_env_var_auto_turns_fallbacks_on_when_keys_and_confirmations_exist(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_CHAT_FALLBACK_ENABLED", "auto")
    settings = _settings(**GEMINI_READY)
    assert settings.gemini_chat_fallback_active is True
    provider = create_background_llm_provider(settings)
    assert isinstance(provider, SequentialFallbackProvider)
    assert provider.backup is not None and provider.backup.name == "opencode-free"
    assert provider.backup2 is not None and provider.backup2.name == "gemini"


def test_key_without_free_plan_confirmation_is_skipped_never_assumed_free() -> None:
    settings = _settings(groq_api_key="gsk-sintetica", gemini_api_key="gm-sintetica")
    assert settings.groq_chat_fallback_active is False
    assert settings.gemini_chat_fallback_active is False
    # Groq exige ademas ZDR confirmado.
    assert _settings(**{**GROQ_READY, "groq_zdr_confirmed": False}).groq_chat_fallback_active is False


def test_explicit_false_keeps_a_configured_fallback_off() -> None:
    settings = _settings(
        **GEMINI_READY,
        opencode_free_chat_fallback_enabled=False,
        gemini_chat_fallback_enabled="false",
    )
    assert settings.opencode_free_chat_fallback_active is False
    assert settings.gemini_chat_fallback_active is False
    assert create_background_llm_provider(settings).name == "opencode-go"


def test_explicit_true_without_key_still_fails_loud_in_chat() -> None:
    with pytest.raises(ValueError, match="Gemini chat requires"):
        create_chat_llm_provider(_settings(gemini_chat_fallback_enabled=True))


def test_auto_does_not_stack_platform_fallbacks_on_the_cascade_provider() -> None:
    # La cascada ya incluye Gemini/OpenRouter; el modo auto solo cubre al Go.
    settings = _settings(llm_provider="cascade", **GROQ_READY, **GEMINI_READY)
    assert settings.groq_chat_fallback_active is False
    assert settings.gemini_chat_fallback_active is False


def test_chat_chain_is_built_in_auto_mode() -> None:
    from app.llm.chat_provider import GEMINI_MODEL, GEMINI_MODEL_2
    chat = create_chat_llm_provider(_settings(**GEMINI_READY))
    backup = getattr(chat, "backup", None)
    assert backup is not None and backup.name == "opencode-free"
    assert chat.backup_model == "deepseek-v4.1-flash-free"
    assert [(p.name, m) for p, m in chat.extra_backups] == [
        ("gemini", GEMINI_MODEL),
        ("gemini", GEMINI_MODEL_2),
    ]


# --- Cascada real con transporte falso --------------------------------------


def test_primary_down_falls_through_to_next_free_provider() -> None:
    upstreams = Upstreams({"go.invalid": 503, "free.invalid": 200})

    async def scenario() -> tuple[str, str, str]:
        async with upstreams.client() as client:
            provider = create_background_llm_provider(
                _settings(
                    opencode_go_base_url="https://go.invalid/v1",
                    opencode_free_base_url="https://free.invalid/v1",
                ),
                client=client,
            )
            assert isinstance(provider, SequentialFallbackProvider)
            provider.retry_pause = 0
            out = await provider.complete(REQ)
            return out.provider, out.model, out.message.content

    name, model, text = asyncio.run(scenario())
    assert name == "opencode-free"
    assert model == "deepseek-v4.1-flash-free"
    assert text == "respuesta de free.invalid"
    assert upstreams.calls[0] == "go.invalid"
    assert upstreams.calls[-1] == "free.invalid"


def test_free_down_falls_through_to_gemini() -> None:
    upstreams = Upstreams(
        {"go.invalid": 500, "free.invalid": 429, "generativelanguage.googleapis.com": 200}
    )

    async def scenario():
        async with upstreams.client() as client:
            provider = create_background_llm_provider(
                _settings(
                    opencode_go_base_url="https://go.invalid/v1",
                    opencode_free_base_url="https://free.invalid/v1",
                    **GEMINI_READY,
                ),
                client=client,
            )
            provider.retry_pause = 0  # pyright: ignore[reportAttributeAccessIssue]
            return await provider.complete(REQ)

    out = asyncio.run(scenario())
    assert out.provider == "gemini"
    assert out.model == GEMINI_MODEL
    assert any(host == "free.invalid" for host in upstreams.calls)


def test_all_providers_down_raises_and_chat_declares_degraded_answer() -> None:
    upstreams = Upstreams(
        {"go.invalid": 503, "free.invalid": 503, "generativelanguage.googleapis.com": 503}
    )

    async def scenario():
        async with upstreams.client() as client:
            provider = create_background_llm_provider(
                _settings(
                    opencode_go_base_url="https://go.invalid/v1",
                    opencode_free_base_url="https://free.invalid/v1",
                    **GEMINI_READY,
                ),
                client=client,
            )
            provider.retry_pause = 0  # pyright: ignore[reportAttributeAccessIssue]
            with pytest.raises(LLMError):
                await provider.complete(REQ)
            return await ChatSynthesisService(provider).synthesize(
                question="q", ticker="AAA", baseline=_baseline()
            )

    result = asyncio.run(scenario())
    # Ningun texto inventado: queda la respuesta determinista, marcada como tal.
    assert result.model == "deterministic"
    assert result.answer == "respuesta determinista"
    assert result.llm_trace["fallback"] is True
    assert set(upstreams.calls) == {
        "go.invalid",
        "free.invalid",
        "generativelanguage.googleapis.com",
    }


# --- LLM_PROVIDER=disabled / LLM_ENABLED=false -----------------------------


@pytest.mark.parametrize(
    ("env", "value"), [("LLM_PROVIDER", "disabled"), ("LLM_ENABLED", "false")]
)
def test_disabled_mode_is_declared_and_never_calls_any_provider(monkeypatch, env, value) -> None:
    monkeypatch.setenv(env, value)
    upstreams = Upstreams({})
    over = {"opencode_go_api_key": "sk-sintetica", **GROQ_READY, **GEMINI_READY}
    settings = Settings(_env_file=None, **over)  # pyright: ignore[reportCallIssue]
    assert llm_configuration_issue(settings) == "disabled_by_configuration"

    async def scenario():
        async with upstreams.client() as client:
            providers = [
                create_llm_provider(settings, client=client),
                create_chat_llm_provider(settings, client=client),
                create_background_llm_provider(settings, client=client),
            ]
            for provider in providers:
                assert provider.name == "disabled"
                with pytest.raises(ProviderDisabledError):
                    await provider.complete(REQ)
            return await ChatSynthesisService(providers[1]).synthesize(
                question="q", ticker="AAA", baseline=_baseline()
            )

    result = asyncio.run(scenario())
    assert upstreams.calls == []
    assert result.model == "deterministic"
    assert result.answer == "respuesta determinista"
    assert result.llm_trace["fallback"] is True
    assert result.llm_trace["fallback_reason"] == "ProviderDisabledError"
