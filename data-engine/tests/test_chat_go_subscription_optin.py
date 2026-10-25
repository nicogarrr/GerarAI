"""Primario de chat por la suscripcion OpenCode Go: apagado por defecto.

Solo mocks (httpx.MockTransport): ninguna llamada real ni trafico de usuario.
"""
from __future__ import annotations

import json

import httpx

from app.core.config import Settings
from app.llm.chat_provider import (
    GO_SUBSCRIPTION_MODEL,
    GO_SUBSCRIPTION_PROVIDER,
    GoSubscriptionChatProvider,
    _go_subscription_primary,
    create_chat_llm_provider,
)
from app.llm.contracts import LLMRequest, Message, ResponseFormat
from app.services.async_bridge import run_from_any_context as run_async

_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


def _settings(**extra) -> Settings:
    base = dict(opencode_go_api_key="test-key-not-real", llm_enabled=True)
    base.update(extra)
    return Settings(**base)


def _ok(content: str) -> dict:
    return {
        "id": "x",
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
    }


def test_apagado_por_defecto():
    settings = _settings()
    assert settings.chat_go_subscription_enabled is False
    assert _go_subscription_primary(settings, None) is None


def test_apagado_no_cambia_el_primario_gratuito():
    provider = create_chat_llm_provider(_settings())
    assert getattr(provider, "name", "") != GO_SUBSCRIPTION_PROVIDER
    assert getattr(getattr(provider, "primary", provider), "name", "") != GO_SUBSCRIPTION_PROVIDER


def test_encendido_sin_clave_no_crea_primario():
    settings = _settings(chat_go_subscription_enabled=True, opencode_go_api_key=None)
    assert _go_subscription_primary(settings, None) is None


def test_sobre_sin_response_format_cabeceras_propias_y_json_desenvuelto():
    seen: dict = {}

    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["headers"] = dict(request.headers)
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=_ok('```json\n{"answer": "ok"}\n```'), request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = _go_subscription_primary(_settings(chat_go_subscription_enabled=True), client)
            assert isinstance(provider, GoSubscriptionChatProvider)
            request = LLMRequest(
                [Message("user", "pregunta")],
                task="chat",
                max_tokens=64,
                response_format=ResponseFormat.json_schema(_SCHEMA, name="t"),
            )
            return await provider.complete(request)

    response = run_async(probe())
    assert seen["url"] == "https://opencode.ai/zen/go/v1/chat/completions"
    assert seen["body"]["model"] == GO_SUBSCRIPTION_MODEL == "deepseek-v4.1-flash"
    assert "response_format" not in seen["body"]
    assert "JSON" in seen["body"]["messages"][-1]["content"]
    assert seen["headers"]["user-agent"] == "GerarAI-chat/1.0"
    assert seen["headers"]["x-opencode-session"]
    assert json.loads(response.text) == {"answer": "ok"}


def test_sin_response_format_el_texto_no_se_toca():
    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["messages"][-1]["content"] == "hola"
            return httpx.Response(200, json=_ok("```texto```"), request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = _go_subscription_primary(_settings(chat_go_subscription_enabled=True), client)
            return await provider.complete(LLMRequest([Message("user", "hola")], task="chat", max_tokens=64))

    assert run_async(probe()).text == "```texto```"


def test_encendido_construye_cadena_con_respaldo_groq():
    settings = _settings(
        chat_go_subscription_enabled=True,
        groq_chat_fallback_enabled=True,
        groq_api_key="g-test",
        groq_free_plan_confirmed=True,
        groq_zdr_confirmed=True,
    )
    provider = create_chat_llm_provider(settings)
    assert provider.primary.name == GO_SUBSCRIPTION_PROVIDER
    assert provider.backup.name == "groq"
