"""Defaults del cerebro aprobado: OpenCode Go + DeepSeek v4.1 Flash.

Solo configuracion: ninguna llamada de red ni generacion.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.llm.chat_provider import GO_SUBSCRIPTION_MODEL, create_chat_llm_provider
from app.llm.factory import create_llm_provider
from app.llm.model_aliases import (
    GO_SUBSCRIPTION_MODELS,
    VERIFIED_FREE_MODELS,
    is_owner_approved_model,
    verified_models,
)
from app.services.llm_router import ROUTES

# Falsa a proposito: el driver lleva +psycopg y el host .invalid, asi el
# detector de formas de secreto no confunde una credencial de test con una real.
_PROD_DB = "postgresql+psycopg://fixture_user:fixture_pass@fixture-db.invalid/fixture_db"
_PROD_SECRET = "research-security-test-secret-at-least-32-chars"


def _settings(**extra) -> Settings:
    base = dict(_env_file=None, opencode_go_api_key="test-key-not-real")
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


def test_defaults_are_the_owner_approved_go_deepseek_model() -> None:
    settings = _settings()
    assert settings.opencode_go_base_url == "https://opencode.ai/zen/go/v1"
    assert settings.opencode_go_model == "deepseek-v4.1-flash"
    assert settings.opencode_go_fallback_model == ""
    assert settings.opencode_go_chat_reasoning_effort == "high"
    assert settings.opencode_go_reasoning_effort == "high"
    assert settings.chat_total_timeout_seconds == 45.0
    assert settings.chat_go_subscription_enabled is True
    assert settings.chat_go_subscription_base_url == "https://opencode.ai/zen/go/v1"
    assert GO_SUBSCRIPTION_MODEL == "deepseek-v4.1-flash"
    assert frozenset({"deepseek-v4.1-flash"}) == GO_SUBSCRIPTION_MODELS
    assert settings.opencode_go_model not in VERIFIED_FREE_MODELS


def test_all_task_routes_resolve_to_the_go_model() -> None:
    assert {route.model for route in ROUTES.values()} == {"deepseek-v4.1-flash"}
    provider = create_llm_provider(_settings())
    assert provider.model_router.default_model == "deepseek-v4.1-flash"


def test_default_chat_provider_is_not_self_disabled() -> None:
    provider = create_chat_llm_provider(_settings())
    # Con la pata free en auto el chat es la cadena; el primario sigue siendo Go.
    primary = getattr(provider, "primary", provider)
    assert primary.name == "opencode-go-subscription"


def test_go_model_is_accepted_only_with_the_subscription_confirmed() -> None:
    enabled = _settings()
    assert is_owner_approved_model("deepseek-v4.1-flash", enabled)
    assert "deepseek-v4.1-flash" in verified_models(enabled)
    disabled = _settings(chat_go_subscription_enabled=False)
    assert not is_owner_approved_model("deepseek-v4.1-flash", disabled)
    assert "deepseek-v4.1-flash" not in verified_models(disabled)
    # Los free reales siguen aceptados sin la suscripcion.
    assert is_owner_approved_model("deepseek-v4.1-flash-free", disabled)


def test_production_rejects_an_unapproved_model_at_startup() -> None:
    with pytest.raises(ValidationError, match="OPENCODE_GO_MODEL is not an owner-approved"):
        _production(opencode_go_model="paid-model-unknown")
    with pytest.raises(ValidationError, match="OPENCODE_GO_FALLBACK_MODEL"):
        _production(opencode_go_fallback_model="paid-model-unknown")


def test_production_allows_approved_models_and_the_explicit_pilot_flag() -> None:
    assert _production().opencode_go_model == "deepseek-v4.1-flash"
    assert _production(opencode_go_model="deepseek-v4.1-flash-free").opencode_go_model
    pilot = _production(
        opencode_go_model="paid-model-unknown",
        opencode_go_allow_unverified_model=True,
    )
    assert pilot.opencode_go_model == "paid-model-unknown"


def test_production_does_not_accept_the_go_model_without_the_subscription() -> None:
    with pytest.raises(ValidationError, match="OPENCODE_GO_MODEL is not an owner-approved"):
        _production(chat_go_subscription_enabled=False)


def test_groq_and_gemini_stay_off_by_default() -> None:
    # Modo auto (hallazgo M1): sin clave ni confirmacion de plan gratuito los
    # respaldos siguen apagados; ver tests/test_llm_degraded_mode.py.
    settings = _settings()
    assert settings.groq_chat_fallback_enabled is None
    assert settings.gemini_chat_fallback_enabled is None
    assert settings.groq_chat_fallback_active is False
    assert settings.gemini_chat_fallback_active is False
