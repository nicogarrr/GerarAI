"""ASTS y traduccion publica de titulares envian reasoning_effort=none por request (piloto Go 2026-10-26: respuesta vacia con effort alto).

Offline: MockTransport captura el payload; ninguna llamada de red."""
import asyncio
import json
from unittest import mock

import httpx

from app.core.config import Settings
from app.llm.factory import create_llm_provider


def _go_provider(captured: list):
    def handler(request: httpx.Request):
        captured.append(json.loads(request.content))
        body = json.dumps({"summary": "ok", "observations": []})
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": body}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, "model": "deepseek-v4.1-flash"})
    settings = Settings(_env_file=None, opencode_go_api_key="k", opencode_go_base_url="https://opencode.ai/zen/go/v1",
                        opencode_go_model="deepseek-v4.1-flash", opencode_go_fallback_model="", llm_model_overrides={},
                        chat_go_subscription_enabled=True)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return create_llm_provider(settings, client=client, max_retries=0), settings


def test_asts_envia_effort_none_y_conserva_limites() -> None:
    from app.services import asts_llm_service as S
    captured: list = []
    provider, settings = _go_provider(captured)
    with mock.patch.object(S, "create_llm_provider", return_value=provider), mock.patch.object(S, "get_settings", return_value=settings):
        asyncio.run(S._analyze_with_llm("SINTETICO"))
    payload = captured[0]
    assert payload["reasoning_effort"] == "none"
    assert payload["max_tokens"] == 900 and payload["temperature"] == 0 and payload["model"] == "deepseek-v4.1-flash"
    assert "response_format" not in payload  # el adaptador Go lo elimina (#2181)


def test_traduccion_publica_envia_effort_none() -> None:
    import app.services.public_headline_translation as H
    captured: list = []
    provider, _ = _go_provider(captured)
    class _Db:
        info = {"tenant_id": "t"}
    H._cache.clear()
    with mock.patch.object(H, "reserve_quota", lambda *a, **k: {"allowed": True}):
        asyncio.run(H.translate_external_headline(_Db(), "Meta Raises 2026 Capex Guidance To $72 Billion Amid AI Push", provider=provider))
    payload = captured[0]
    assert payload["reasoning_effort"] == "none" and payload["max_tokens"] == 240
