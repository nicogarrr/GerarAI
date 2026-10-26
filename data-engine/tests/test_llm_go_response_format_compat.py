"""Compatibilidad del endpoint Go (/zen/go/v1) con salida estructurada.

Verificado en vivo por el piloto (2026-10-26): deepseek-v4.1-flash responde
HTTP 400 a `response_format` con json_schema estricto; json_object/plain 200.
El provider opencode-go general (narrativa de tesis, KPI, ASTS, second-order)
retira el sobre y pide el contrato en el prompt, como ya hacia el chat; la
validacion local fail-closed de cada llamador sigue siendo la puerta.
"""

import asyncio
import json

import httpx

from app.core.config import Settings
from app.llm import (
    LLMRequest,
    Message,
    OpenAICompatibleProvider,
    ResponseFormat,
    create_llm_provider,
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"secciones": {"type": "array", "items": {"type": "string"}}},
    "required": ["secciones"],
}


def run(coroutine):
    return asyncio.run(coroutine)


def _provider(handler, **settings_extra):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = create_llm_provider(
                Settings(
                    _env_file=None,
                    opencode_go_api_key="test-secret",
                    opencode_go_base_url="https://opencode.test/zen/go/v1",
                    **settings_extra,
                ),
                client=client,
            )
            return await provider.complete(
                LLMRequest(
                    messages=[Message("system", "Clasifica."), Message("user", "Extrae")],
                    task="cheap_extraction",
                    response_format=ResponseFormat.json_schema(SCHEMA, name="out"),
                )
            )

    return run(scenario())


def _ok(text):
    def handler(_request):
        return httpx.Response(
            200,
            json={
                "id": "r",
                "model": "deepseek-v4.1-flash",
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )
    return handler


def test_opencode_go_strips_response_format_and_moves_contract_to_prompt():
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return _ok("{}")(request)

    _provider(handler)

    # El sobre NO viaja: el endpoint 400 queda fuera de juego.
    assert "response_format" not in captured
    # El contrato (con el esquema) viaja en el ultimo mensaje de usuario.
    last_user = captured["messages"][-1]
    assert last_user["role"] == "user"
    assert "Responde SOLO con un objeto JSON valido" in last_user["content"]
    assert '"secciones"' in last_user["content"]
    assert last_user["content"].startswith("Extrae")


def test_opencode_go_unwraps_fenced_json_for_local_validators():
    fenced = '```json\n{"secciones": ["a"]}\n```'
    response = _provider(_ok(fenced))
    assert response.text == '{"secciones": ["a"]}'


def test_plain_openai_compatible_provider_keeps_strict_json_schema():
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return _ok("{}")(request)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                api_key="k",
                base_url="https://provider.test/v1",
                default_model="m",
                provider_name="other",
                client=client,
            )
            return await provider.complete(
                LLMRequest(
                    messages=[Message("user", "Extrae")],
                    response_format=ResponseFormat.json_schema(SCHEMA, name="out"),
                )
            )

    run(scenario())
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True


def test_request_messages_are_not_mutated_by_the_quirk():
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return _ok("{}")(request)

    messages = [Message("user", "Extrae")]
    request = LLMRequest(
        messages=messages,
        task="cheap_extraction",
        response_format=ResponseFormat.json_schema(SCHEMA, name="out"),
    )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = create_llm_provider(
                Settings(
                    _env_file=None,
                    opencode_go_api_key="test-secret",
                    opencode_go_base_url="https://opencode.test/zen/go/v1",
                ),
                client=client,
            )
            await provider.complete(request)

    run(scenario())
    assert request.messages[0].content == "Extrae"
