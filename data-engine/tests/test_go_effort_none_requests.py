"""ASTS y traduccion publica de titulares envian el esfuerzo de su seccion (tabla por seccion: low)
con topes que dejan sitio al razonamiento (piloto Go 2026-10-26: con effort alto y topes cortos
la respuesta llegaba vacia).

Offline: MockTransport captura el payload; ninguna llamada de red."""
import asyncio
import json
from unittest import mock

import httpx
import pytest

from app.core.config import Settings
from app.llm.factory import create_llm_provider


@pytest.fixture(autouse=True)
def _no_llm_response_cache(monkeypatch):
    monkeypatch.setenv("LLM_RESPONSE_CACHE_ENABLED", "false")


def _go_provider(captured: list):
    def handler(request: httpx.Request):
        captured.append(json.loads(request.content))
        body = json.dumps({"summary": "ok", "observations": []})
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": body}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "model": "deepseek-v4.1-flash"})
    settings = Settings(_env_file=None, llm_enabled=True, opencode_go_api_key="k", opencode_go_base_url="https://opencode.ai/zen/go/v1",
                        opencode_go_model="deepseek-v4.1-flash", opencode_go_fallback_model="", llm_model_overrides={},
                        chat_go_subscription_enabled=True)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return create_llm_provider(settings, client=client, max_retries=0), settings


@pytest.mark.parametrize("ambient_llm_enabled", ["false", "true"])
def test_traduccion_publica_envia_effort_de_la_tabla(monkeypatch, ambient_llm_enabled) -> None:
    # Payload-contract test: always use the local MockTransport provider,
    # even when the VM disables real LLM traffic for its offline gates.
    monkeypatch.setenv("LLM_ENABLED", ambient_llm_enabled)
    import app.services.public_headline_translation as H
    captured: list = []
    provider, _ = _go_provider(captured)
    class _Db:
        info = {"tenant_id": "t"}
    H._cache.clear()
    with mock.patch.object(H, "reserve_quota", lambda *a, **k: {"allowed": True}):
        asyncio.run(H.translate_external_headline(_Db(), "Meta Raises 2026 Capex Guidance To $72 Billion Amid AI Push", provider=provider))
    assert len(captured) == 1, "the injected MockTransport must receive exactly one request"
    payload = captured[0]
    assert payload["reasoning_effort"] == "low" and payload["max_tokens"] >= 600
