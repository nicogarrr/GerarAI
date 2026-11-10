"""Invalid persisted tenant LLM settings stay explicit and fail closed."""

import pytest

from app.core.config import Settings
from app.models import TenantLLMSettings
from app.services import tenant_llm_settings_service as svc


@pytest.fixture
def settings():
    return Settings(_env_file=None, app_env="test", llm_settings_encryption_key=None)


def row(**overrides):
    values = dict(
        tenant_id=1,
        provider="openai",
        model="test-model",
        enabled=True,
        base_url=None,
        fallback_model=None,
        reasoning_effort=None,
        api_key_ciphertext=None,
    )
    values.update(overrides)
    return TenantLLMSettings(**values)


@pytest.mark.parametrize(
    "overrides,error",
    [
        ({"provider": "custom", "base_url": "http://127.0.0.1"}, "tenant_llm_base_url_invalid"),
        ({"model": ""}, "tenant_llm_model_invalid"),
        ({"fallback_model": "bad\nmodel"}, "tenant_llm_fallback_model_invalid"),
        ({"reasoning_effort": "impossible"}, "tenant_llm_reasoning_effort_invalid"),
    ],
)
def test_bad_persisted_field_is_not_platform_fallback(settings, overrides, error):
    config = svc.config_from_row(row(**overrides), settings)
    assert config.error == error and config.billing_scope == "tenant"
    assert config.api_key is None and not config.has_api_key


@pytest.mark.parametrize(
    "available,error",
    [(False, "llm_settings_encryption_not_configured"), (True, "tenant_llm_settings_corrupt")],
)
def test_unreadable_key_never_becomes_usable(settings, monkeypatch, available, error):
    monkeypatch.setattr(svc, "encryption_available", lambda s: available)

    def corrupt(*args):
        raise svc.LLMSettingsCryptoError("invalid synthetic ciphertext")

    monkeypatch.setattr(svc, "decrypt_api_key", corrupt)
    config = svc.config_from_row(row(api_key_ciphertext="invalid-synthetic-ciphertext"), settings)
    assert config.error == error and config.api_key is None and not config.has_api_key


@pytest.mark.parametrize(
    "payload,expected",
    [
        ([], None),
        ({}, None),
        ({"data": "wrong"}, None),
        ({"data": []}, set()),
        ({"data": [None, {}, {"id": 123}]}, None),
        ({"data": [{"id": "model-a"}, {"id": "model-a"}, None]}, {"model-a"}),
    ],
)
def test_model_ids_distinguishes_empty_valid_list_from_unreadable(payload, expected):
    import httpx

    assert svc._model_ids(httpx.Response(200, json=payload)) == expected
