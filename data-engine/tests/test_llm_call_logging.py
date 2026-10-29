"""Registro `llm.call`: una linea por llamada con proveedor, modelo y razonamiento.

#2381 anadio el registro y dejo este fichero vacio. Estos tests fijan lo que
el registro promete (verificar en los logs de produccion que cada llamada fue
a OpenCode Go con DeepSeek V4.1 Flash y el nivel esperado) y lo que nunca
puede pasar: que la clave, o algo con forma de clave, acabe escrita en el log,
venga del campo que venga (modelo devuelto por el proveedor, modelo pedido,
tarea, error).

Todo con `httpx.MockTransport`: sin red y sin claves reales.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import pytest

from app.llm.adapters import OpenAICompatibleProvider
from app.llm.contracts import LLMRequest, Message
from app.services import tracing

FAKE_KEY = "sk-fakeKEY-for-tests-0123456789"
HEADER_SECRET = "hdr-secret-ABCDEFG987654"
LOGGER = "app.llm.adapters"


def _completion(model: str, *, reasoning_tokens: int = 7) -> dict[str, Any]:
    return {
        "id": "cmpl-1",
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "hola"},
            }
        ],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 5,
            "total_tokens": 16,
            "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
        },
    }


def _provider(
    handler,
    *,
    reasoning_effort: str | None = "high",
    reasoning_effort_models: set[str] | None = None,
    default_model: str = "deepseek-v4.1-flash",
) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_key=FAKE_KEY,
        base_url="https://opencode.ai/zen/go/v1",
        default_model=default_model,
        provider_name="opencode-go",
        extra_headers={"x-session-secret": HEADER_SECRET},
        reasoning_effort=reasoning_effort,
        reasoning_effort_models=reasoning_effort_models,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )


def _request(**kwargs: Any) -> LLMRequest:
    kwargs.setdefault("task", "chat")
    return LLMRequest(messages=[Message("user", "¿qué riesgo tengo?")], cache=False, **kwargs)


def _call_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER and r.getMessage().startswith("llm.call")]


def _fields(record: logging.LogRecord) -> dict[str, str]:
    parts = record.getMessage().split(" ")[1:]
    return dict(part.split("=", 1) for part in parts)


def _run(provider: OpenAICompatibleProvider, request: LLMRequest):
    return asyncio.run(provider.complete(request))


# --- Lo que el registro registra ---------------------------------------------


def test_exito_registra_proveedor_modelo_effort_tarea_y_host(caplog):
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=_completion("deepseek-v4.1-flash"))

    with caplog.at_level(logging.INFO, logger=LOGGER):
        _run(_provider(handler), _request())

    (record,) = _call_lines(caplog)
    assert record.levelno == logging.INFO
    fields = _fields(record)
    assert fields["provider"] == "opencode-go"
    assert fields["model"] == "deepseek-v4.1-flash"
    assert fields["requested_model"] == "deepseek-v4.1-flash"
    assert fields["reasoning_effort"] == "high"
    assert fields["task"] == "chat"
    assert fields["status"] == "ok"
    assert fields["host"] == "opencode.ai"
    assert fields["key_scope"] == "platform"
    assert fields["fallback_from"] == "-"
    assert fields["output_tokens"] == "5"
    assert fields["reasoning_tokens"] == "7"
    assert fields["error"] == "-"
    assert int(fields["duration_ms"]) >= 0
    # Lo registrado es lo que de verdad viajo en el sobre.
    assert sent[0]["reasoning_effort"] == "high"
    assert sent[0]["model"] == "deepseek-v4.1-flash"


def test_effort_por_request_gana_al_del_proveedor(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("deepseek-v4.1-flash"))

    with caplog.at_level(logging.INFO, logger=LOGGER):
        _run(_provider(handler, reasoning_effort="high"), _request(reasoning_effort="low"))

    assert _fields(_call_lines(caplog)[0])["reasoning_effort"] == "low"


def test_effort_que_no_se_envia_se_registra_como_none_sent(caplog):
    """Un modelo fuera de reasoning_effort_models no recibe el nivel: el log no miente."""
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=_completion("otro-modelo"))

    provider = _provider(
        handler,
        reasoning_effort="max",
        reasoning_effort_models={"deepseek-v4.1-flash"},
    )
    with caplog.at_level(logging.INFO, logger=LOGGER):
        _run(provider, _request(model="otro-modelo"))

    assert sent[0]["model"] == "otro-modelo"
    assert "reasoning_effort" not in sent[0]
    assert _fields(_call_lines(caplog)[0])["reasoning_effort"] == "none_sent"


def test_modelo_devuelto_distinto_del_pedido_se_ve(caplog):
    """Si el proveedor sirve otro modelo, el registro lo muestra al lado del pedido."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("deepseek-v4-flash-0901"))

    with caplog.at_level(logging.INFO, logger=LOGGER):
        _run(_provider(handler), _request())

    fields = _fields(_call_lines(caplog)[0])
    assert fields["model"] == "deepseek-v4-flash-0901"
    assert fields["requested_model"] == "deepseek-v4.1-flash"


def test_clave_de_tenant_se_registra_como_ambito_no_como_clave(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("deepseek-v4.1-flash"))

    provider = _provider(handler)
    provider.billing_scope = "tenant"
    with caplog.at_level(logging.INFO, logger=LOGGER):
        _run(provider, _request())

    assert _fields(_call_lines(caplog)[0])["key_scope"] == "tenant"
    assert FAKE_KEY not in caplog.text


# --- Camino de fallo ------------------------------------------------------------


def test_fallo_http_registra_warning_con_clase_de_error_y_sin_clave(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"Invalid API key: {FAKE_KEY}")

    with caplog.at_level(logging.INFO):
        with pytest.raises(Exception):
            _run(_provider(handler), _request())

    (record,) = _call_lines(caplog)
    assert record.levelno == logging.WARNING
    fields = _fields(record)
    assert fields["status"] == "failed"
    assert fields["error"] == "ProviderHTTPError"
    assert fields["output_tokens"] == "-"
    assert fields["reasoning_tokens"] == "-"
    assert fields["provider"] == "opencode-go"
    assert fields["requested_model"] == "deepseek-v4.1-flash"
    assert FAKE_KEY not in caplog.text
    assert HEADER_SECRET not in caplog.text


def test_fallo_de_red_registra_la_clase_de_excepcion(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with caplog.at_level(logging.INFO, logger=LOGGER):
        with pytest.raises(Exception):
            _run(_provider(handler), _request())

    fields = _fields(_call_lines(caplog)[0])
    assert fields["status"] == "failed"
    assert fields["error"] not in {"", "-"}


def test_cancelacion_no_se_registra_como_fallo(caplog):
    async def scenario() -> None:
        started = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            started.set()
            await asyncio.sleep(10)
            return httpx.Response(200, json=_completion("deepseek-v4.1-flash"))

        provider = _provider(handler)
        task = asyncio.create_task(provider.complete(_request()))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with caplog.at_level(logging.INFO, logger=LOGGER):
        asyncio.run(scenario())

    (record,) = _call_lines(caplog)
    assert record.levelno == logging.INFO
    fields = _fields(record)
    assert fields["status"] == "cancelled"
    assert fields["error"] == "-"


# --- Ninguna clave en el registro, venga del campo que venga --------------------


@pytest.mark.parametrize(
    "returned_model,leak",
    [
        (FAKE_KEY, FAKE_KEY),  # la clave exacta del proveedor
        (f"deepseek {HEADER_SECRET}", HEADER_SECRET),  # una cabecera conocida
        ("sk-proj-OTRACLAVEFILTRADA123", "OTRACLAVEFILTRADA123"),  # patron sk-
        ("Bearer abc.DEF-123_xyz", "abc.DEF-123_xyz"),  # patron Bearer
        ("api_key=zzTOPSECRET99", "zzTOPSECRET99"),  # patron api_key=
    ],
)
def test_modelo_devuelto_con_secreto_se_redacta(caplog, returned_model, leak):
    """El campo `model` lo escribe el proveedor: nunca se registra tal cual."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion(returned_model))

    with caplog.at_level(logging.INFO, logger=LOGGER):
        _run(_provider(handler), _request())

    assert leak not in caplog.text
    assert "[REDACTED]" in _fields(_call_lines(caplog)[0])["model"]


def test_modelo_pedido_y_tarea_con_secreto_se_redactan(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("deepseek-v4.1-flash"))

    with caplog.at_level(logging.INFO, logger=LOGGER):
        _run(
            _provider(handler),
            _request(model=f"modelo-{FAKE_KEY}", task=f"chat token={FAKE_KEY}"),
        )

    fields = _fields(_call_lines(caplog)[0])
    assert "[REDACTED]" in fields["requested_model"]
    assert "[REDACTED]" in fields["task"]
    assert FAKE_KEY not in caplog.text


def test_un_valor_no_puede_inyectar_campos_falsos_en_la_linea(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("evil status=ok\nllm.call provider=x"))

    with caplog.at_level(logging.INFO, logger=LOGGER):
        _run(_provider(handler), _request())

    (record,) = _call_lines(caplog)
    message = record.getMessage()
    assert "\n" not in message
    assert message.count(" status=") == 1
    assert message.count(" provider=") == 1
    assert _fields(record)["status"] == "ok"
    assert _fields(record)["provider"] == "opencode-go"


def test_un_modelo_enorme_se_trunca(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("m" * 5000))

    with caplog.at_level(logging.INFO, logger=LOGGER):
        _run(_provider(handler), _request())

    assert len(_fields(_call_lines(caplog)[0])["model"]) <= 120


def test_la_traza_tampoco_lleva_el_secreto(monkeypatch):
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(tracing, "trace_generation", lambda **kw: seen.append(kw))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion(FAKE_KEY))

    _run(_provider(handler), _request())

    assert seen, "la llamada debe abrir un span de generacion"
    assert FAKE_KEY not in json.dumps(seen, default=str)


def test_nunca_registra_prompt_ni_respuesta(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("deepseek-v4.1-flash"))

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        _run(_provider(handler), _request())

    line = _call_lines(caplog)[0].getMessage()
    assert "riesgo" not in line
    assert "hola" not in line


# --- El modelo que se PERSISTE (budget_usage, telemetria, ChatResponse) -------
# El registro `llm.call` ya redactaba; el mismo valor viajaba sin tocar a la
# respuesta y de ahi a Postgres (String(160)) y al frontend.


@pytest.mark.parametrize(
    "returned_model,leak",
    [
        (FAKE_KEY, FAKE_KEY),
        (f"deepseek {HEADER_SECRET}", HEADER_SECRET),
        ("sk-proj-OTRACLAVEFILTRADA123", "OTRACLAVEFILTRADA123"),
        ("api_key=zzTOPSECRET99", "zzTOPSECRET99"),
    ],
)
def test_modelo_persistido_de_la_respuesta_se_redacta(returned_model, leak):
    """LLMResponse.model se persiste y se muestra: mismas reglas que el log."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion(returned_model))

    response = _run(_provider(handler), _request())
    assert leak not in response.model
    assert "[REDACTED]" in response.model


def test_modelo_persistido_acotado_a_la_columna():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("x" * 5000))

    response = _run(_provider(handler), _request())
    assert len(response.model) <= 160


def test_modelo_persistido_vacio_conserva_el_pedido():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion(""))

    response = _run(_provider(handler), _request())
    assert response.model == "deepseek-v4.1-flash"
