"""Primario de chat por la suscripcion OpenCode Go: encendido por decision del dueno.

El interruptor sigue permitiendo volver a la ruta free. Solo mocks
(httpx.MockTransport): ninguna llamada real ni trafico de usuario.
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


def test_encendido_por_defecto_por_decision_del_dueno():
    settings = _settings()
    assert settings.chat_go_subscription_enabled is True
    assert isinstance(_go_subscription_primary(settings, None), GoSubscriptionChatProvider)


def test_apagado_vuelve_a_la_ruta_free_verificada():
    provider = create_chat_llm_provider(
        _settings(
            chat_go_subscription_enabled=False,
            opencode_go_model="deepseek-v4.1-flash-free",
        )
    )
    assert getattr(provider, "name", "") == "opencode-go"
    assert getattr(provider, "name", "") != GO_SUBSCRIPTION_PROVIDER


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


def test_encendido_construye_cadena_con_respaldo_free():
    # Cadena 2026-11-01: Go -> OpenCode free (misma clave Go) -> Gemini.
    settings = _settings(chat_go_subscription_enabled=True)
    provider = create_chat_llm_provider(settings)
    assert provider.primary.name == GO_SUBSCRIPTION_PROVIDER
    assert provider.backup.name == "opencode-free"
    assert provider.backup_model == "deepseek-v4.1-flash-free"


# --- Carrera Go (primario) vs Groq (respaldo): ventaja, errores y citas -----------
import asyncio  # noqa: E402

from app.llm.chat_provider import ChatFallbackProvider, _groq_backup  # noqa: E402


def _race_settings(**extra) -> Settings:
    return _settings(
        chat_go_subscription_enabled=True,
        groq_chat_fallback_enabled=True,
        groq_api_key="g-test",
        groq_free_plan_confirmed=True,
        groq_zdr_confirmed=True,
        **extra,
    )


def _race(go_delay: float, go_status: int, delay: float, go_text: str = "Go [S1]") -> str:
    async def probe():
        async def go_handler(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(go_delay)
            if go_status != 200:
                return httpx.Response(go_status, json={"error": "x"}, request=request)
            return httpx.Response(200, json=_ok(go_text), request=request)

        async def groq_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok("Groq [S1]"), request=request)

        settings = _race_settings()
        async with httpx.AsyncClient(transport=httpx.MockTransport(go_handler)) as go_client, \
                httpx.AsyncClient(transport=httpx.MockTransport(groq_handler)) as groq_client:
            primary = _go_subscription_primary(settings, go_client)
            backup = _groq_backup(settings, groq_client)
            chain = ChatFallbackProvider(primary, backup, total=10, delay=delay)
            response = await chain.complete(LLMRequest([Message("user", "q")], task="chat", max_tokens=64))
            return response.text

    return run_async(probe())


def test_go_gana_si_responde_dentro_de_su_ventaja():
    assert _race(go_delay=0.2, go_status=200, delay=2.0) == "Go [S1]"


def test_ventaja_corta_deja_ganar_a_groq_comportamiento_medido_en_prod():
    assert _race(go_delay=0.6, go_status=200, delay=0.1) == "Groq [S1]"


def test_si_go_falla_groq_responde_sin_esperar_la_ventaja():
    import time

    start = time.monotonic()
    assert _race(go_delay=0.0, go_status=500, delay=5.0) == "Groq [S1]"
    assert time.monotonic() - start < 3.0


def test_go_tiene_dos_tercios_del_plazo_antes_del_respaldo():
    settings = _race_settings()
    chain = create_chat_llm_provider(settings)
    assert chain.primary.name == GO_SUBSCRIPTION_PROVIDER
    # Sin carrera: Go tiene 2/3 del presupuesto del chat antes del respaldo.
    assert chain.delay == settings.chat_total_timeout_seconds * 2 / 3
    # Con la suscripcion apagada (ruta legacy free) el primario ES ya el
    # modelo free: no hay pata free extra y, sin Gemini, queda a secas.
    off = create_chat_llm_provider(_settings(
        chat_go_subscription_enabled=False,
        opencode_go_model="deepseek-v4.1-flash-free",
    ))
    assert off.name == "opencode-go"


def test_go_primario_eleva_max_tokens_a_2600_sin_tocar_otros_proveedores():
    settings = _race_settings()
    chain = create_chat_llm_provider(settings)
    request = LLMRequest([Message("user", "hola")], max_tokens=1800)
    go_payload = chain.primary._build_payload(request, GO_SUBSCRIPTION_MODEL)
    assert settings.chat_go_min_output_tokens == 2600
    assert go_payload["max_tokens"] == 2600
    big = chain.primary._build_payload(LLMRequest([Message("user", "hola")], max_tokens=3000), GO_SUBSCRIPTION_MODEL)
    assert big["max_tokens"] == 3000
    assert settings.llm_hidden_reasoning_min_tokens == 1024


def test_go_compact_hint_only_for_the_sections_schema_and_not_mutating_request():
    from app.llm.chat_provider import GO_COMPACT_SECTIONS_HINT
    from app.services.chat_synthesis_service import RESPONSE_SCHEMA

    provider = _go_subscription_primary(_settings(chat_go_subscription_enabled=True), None)
    rich = LLMRequest(
        [Message("system", "s"), Message("user", "q")],
        max_tokens=1800,
        response_format=ResponseFormat.json_schema(RESPONSE_SCHEMA, name="source_aware_chat", strict=True),
    )
    before = rich.messages[-1].content
    payload = provider._build_payload(rich, GO_SUBSCRIPTION_MODEL)
    last = payload["messages"][-1]["content"]
    assert GO_COMPACT_SECTIONS_HINT in last and "response_format" not in payload
    assert "8 apartados" in last and "citas exactas" in last
    assert rich.messages[-1].content == before  # request intact (also for other providers)
    simple = LLMRequest(
        [Message("user", "q")],
        response_format=ResponseFormat.json_schema(_SCHEMA, name="x", strict=True),
    )
    assert GO_COMPACT_SECTIONS_HINT not in provider._build_payload(simple, GO_SUBSCRIPTION_MODEL)["messages"][-1]["content"]


def test_go_compact_hint_requires_exactly_eight_sections():
    from app.llm.chat_provider import GO_COMPACT_SECTIONS_HINT

    provider = _go_subscription_primary(_settings(chat_go_subscription_enabled=True), None)
    for items in ({"type": "array"}, {"type": "array", "minItems": 3, "maxItems": 3}, {"type": "array", "minItems": 8, "maxItems": 9}):
        schema = {"type": "object", "properties": {"sections": items, "answer": {"type": "string"}}}
        req = LLMRequest([Message("user", "q")], response_format=ResponseFormat.json_schema(schema, name="x", strict=True))
        assert GO_COMPACT_SECTIONS_HINT not in provider._build_payload(req, GO_SUBSCRIPTION_MODEL)["messages"][-1]["content"]
