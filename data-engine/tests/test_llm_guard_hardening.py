"""Guards de produccion del cerebro: overrides, cascade, fallback Go y disabled."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml
from pydantic import ValidationError

from app.core.config import Settings
from app.llm.chat_provider import _go_subscription_primary, create_chat_llm_provider
from app.llm.contracts import LLMRequest, Message
from app.llm.readiness import llm_configuration_issue
from app.services.async_bridge import run_from_any_context as run_async

_PROD_DB = "postgresql+psycopg://fixture_user:fixture_pass@fixture-db.invalid/fixture_db"
_PROD_SECRET = "research-security-test-secret-at-least-32-chars"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _settings(**extra) -> Settings:
    base = dict(_env_file=None, app_env="test", opencode_go_api_key="test-key-not-real")
    base.update(extra)
    return Settings(**base)


def _production(**extra) -> Settings:
    base = dict(
        _env_file=None,
        app_env="production",
        research_auth_required=True,
        research_auth_secret=_PROD_SECRET,
        minio_access_key="production-minio-access-not-a-default",
        minio_secret_key="production-minio-secret-not-a-default",
        database_url=_PROD_DB,
        opencode_go_api_key="test-key-not-real",
    )
    base.update(extra)
    return Settings(**base)


def _ok(content: str = "ok") -> dict:
    return {
        "id": "x",
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
    }


def test_production_rejects_paid_model_override_at_startup() -> None:
    with pytest.raises(ValidationError, match="LLM_MODEL_OVERRIDES"):
        _production(llm_model_overrides={"chat": "paid-model-unknown"})


def test_production_accepts_approved_override_and_the_pilot_flag() -> None:
    approved = _production(llm_model_overrides={"chat": "deepseek-v4.1-flash"})
    assert approved.llm_model_overrides == {"chat": "deepseek-v4.1-flash"}
    pilot = _production(
        llm_model_overrides={"chat": "paid-model-unknown"},
        opencode_go_allow_unverified_model=True,
    )
    assert pilot.llm_model_overrides == {"chat": "paid-model-unknown"}


def test_readiness_blocks_paid_model_override() -> None:
    assert (
        llm_configuration_issue(
            _settings(llm_model_overrides={"chat": "paid-model-unknown"})
        )
        == "llm_model_override_not_owner_approved"
    )
    assert (
        llm_configuration_issue(
            _settings(
                llm_model_overrides={"chat": "paid-model-unknown"},
                opencode_go_allow_unverified_model=True,
            )
        )
        is None
    )


def test_production_cascade_rejects_paid_members() -> None:
    with pytest.raises(ValidationError, match="GEMINI_FREE_PLAN_CONFIRMED"):
        _production(llm_provider="cascade", gemini_api_key="gemini-test-key")
    with pytest.raises(ValidationError, match="OpenRouter :free"):
        _production(
            llm_provider="cascade",
            openrouter_api_key="openrouter-test-key",
            openrouter_model="paid/model",
        )
    with pytest.raises(ValidationError, match="owner-approved OpenCode Go model"):
        _production(llm_provider="cascade", opencode_go_model="paid-model-unknown")
    with pytest.raises(ValidationError, match="at least one provider key"):
        _production(llm_provider="cascade", opencode_go_api_key=None)


def test_production_cascade_accepts_a_fully_free_chain() -> None:
    settings = _production(
        llm_provider="cascade",
        gemini_api_key="gemini-test-key",
        gemini_free_plan_confirmed=True,
        openrouter_api_key="openrouter-test-key",
        openrouter_model="google/gemma-4-31b-it:free",
    )
    assert settings.llm_provider == "cascade"


def test_readiness_cascade_rejects_paid_members() -> None:
    assert (
        llm_configuration_issue(
            _settings(llm_provider="cascade", gemini_api_key="gemini-test-key")
        )
        == "cascade_gemini_free_plan_not_confirmed"
    )
    assert (
        llm_configuration_issue(
            _settings(
                llm_provider="cascade",
                openrouter_api_key="openrouter-test-key",
                openrouter_model="paid/model",
            )
        )
        == "cascade_openrouter_model_not_free"
    )
    assert (
        llm_configuration_issue(
            _settings(llm_provider="cascade", opencode_go_model="paid-model-unknown")
        )
        == "cascade_opencode_go_model_not_owner_approved"
    )


def test_readiness_cascade_accepts_a_fully_free_chain() -> None:
    assert (
        llm_configuration_issue(
            _settings(
                llm_provider="cascade",
                gemini_api_key="gemini-test-key",
                gemini_free_plan_confirmed=True,
                openrouter_api_key="openrouter-test-key",
                openrouter_model="google/gemma-4-31b-it:free",
            )
        )
        is None
    )


def test_go_chat_uses_the_configured_fallback_model() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        seen.append(model)
        if model == "deepseek-v4.1-flash":
            return httpx.Response(500, json={"error": "primary down"}, request=request)
        return httpx.Response(200, json=_ok("respuesta de respaldo"), request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = create_chat_llm_provider(
                _settings(opencode_go_fallback_model="deepseek-v4.1-flash-free"),
                client=client,
            )
            return await provider.complete(
                LLMRequest([Message("user", "hola")], task="chat", max_tokens=64)
            )

    response = run_async(run())
    assert response.text == "respuesta de respaldo"
    assert seen == ["deepseek-v4.1-flash", "deepseek-v4.1-flash-free"]


def test_disabled_provider_does_not_build_the_go_primary(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("a disabled provider must not build the Go primary")

    monkeypatch.setattr("app.llm.chat_provider._go_subscription_primary", fail)
    provider = create_chat_llm_provider(_settings(llm_provider="disabled"))
    assert provider.name == "disabled"
    assert getattr(provider, "reason", None) == "disabled_by_configuration"


def test_go_chat_primary_wires_the_tenant_scoped_cache(monkeypatch) -> None:
    monkeypatch.setenv("LLM_RESPONSE_CACHE_ENABLED", "true")
    provider = _go_subscription_primary(_settings(), None)
    assert provider is not None
    assert provider._response_cache is not None
    assert provider._response_cache.require_tenant is True


def test_local_compose_defaults_match_the_go_brain() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for service in ("backend", "worker", "scheduler", "frontend"):
        values = {
            str(entry).partition("=")[0]: str(entry).partition("=")[2]
            for entry in compose["services"][service]["environment"]
        }
        assert values["OPENCODE_GO_BASE_URL"] == (
            "${OPENCODE_GO_BASE_URL:-https://opencode.ai/zen/go/v1}"
        )
        assert values["OPENCODE_GO_MODEL"] == "${OPENCODE_GO_MODEL:-deepseek-v4.1-flash}"


def test_qa_e2e_precheck_uses_the_go_endpoint_and_model() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "qa-e2e.yml").read_text(encoding="utf-8")
    assert "https://opencode.ai/zen/go/v1" in text
    assert "${ZEN_MODEL:-deepseek-v4.1-flash}" in text
    assert "space-bunny-free" not in text
