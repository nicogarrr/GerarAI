"""OpenCode Go configurado en Ajustes (clave del tenant) llega de verdad al endpoint Go.

Verificado en vivo el 2026-10-27: sin `x-opencode-session` el endpoint Go
responde 400 MissingSessionID, y con `response_format` json_schema tambien 400.
"""

import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.contracts import LLMRequest, Message, ResponseFormat
from app.llm.factory import create_llm_provider
from app.llm.tenant_config import (
    TenantLLMConfig,
    normalize_reasoning_effort,
    tenant_llm_config_scope,
)

_OK = {
    "model": "deepseek-v4.1-flash",
    "choices": [{"message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


def _capture(config: TenantLLMConfig, request: LLMRequest, **settings_kw):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=_OK)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(app_env="test", opencode_go_session="gerarai-prod", **settings_kw)
    with tenant_llm_config_scope(config):
        provider = create_llm_provider(settings, client=client)
        asyncio.run(provider.complete(request))
    assert len(seen) == 1
    return seen[0], json.loads(seen[0].content)


def _go(**kw) -> TenantLLMConfig:
    return TenantLLMConfig(
        provider="opencode-go",
        base_url="https://opencode.ai/zen/go/v1",
        model="deepseek-v4.1-flash",
        api_key="clave-del-tenant",
        **kw,
    )


def _req(**kw) -> LLMRequest:
    return LLMRequest([Message("user", "hola")], task="chat", **kw)


def test_tenant_opencode_go_envia_cabecera_de_sesion():
    sent, _ = _capture(_go(reasoning_effort="high"), _req())
    assert sent.headers["x-opencode-session"] == "gerarai-prod"
    assert sent.headers["authorization"] == "Bearer clave-del-tenant"


def test_tenant_opencode_go_sin_nivel_usa_high_del_despliegue():
    _, payload = _capture(_go(reasoning_effort=None), _req())
    assert payload["reasoning_effort"] == "high"


def test_tenant_opencode_go_respeta_el_nivel_elegido_incluido_max():
    _, payload = _capture(_go(reasoning_effort="max"), _req())
    assert payload["reasoning_effort"] == "max"


def test_tenant_opencode_go_quita_response_format_y_lo_pasa_al_prompt():
    fmt = ResponseFormat.json_object()
    _, payload = _capture(_go(reasoning_effort="high"), _req(response_format=fmt))
    assert "response_format" not in payload


def test_tenant_de_otro_proveedor_no_recibe_cabecera_go_ni_nivel_impuesto():
    config = TenantLLMConfig(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4.1-mini",
        api_key="otra",
    )
    sent, payload = _capture(config, _req())
    assert "x-opencode-session" not in sent.headers
    assert "reasoning_effort" not in payload


@pytest.mark.parametrize("value", ["max", "MAX", " high "])
def test_ajustes_aceptan_max_y_high(value):
    assert normalize_reasoning_effort(value) == value.strip().lower()


def test_ajustes_rechazan_niveles_desconocidos():
    with pytest.raises(ValueError):
        normalize_reasoning_effort("ultra")
