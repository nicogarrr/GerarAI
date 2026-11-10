"""A legacy unknown provider must return an unusable tenant config, not KeyError."""
import pytest

from app.core.config import Settings
from app.models import TenantLLMSettings
from app.services import tenant_llm_settings_service as svc


@pytest.mark.parametrize("provider", ["unknown", "", "  unsupported  "])
def test_unknown_provider_never_raises_or_decrypts_a_key(monkeypatch, provider):
    def no_key(*args):
        pytest.fail("invalid-provider config must not fetch or decrypt a real key")

    monkeypatch.setattr(svc, "decrypt_api_key", no_key)
    row = TenantLLMSettings(tenant_id=1, provider=provider, model="test-model", base_url=None,
                            enabled=True, api_key_ciphertext=None, reasoning_effort=None)
    config = svc.config_from_row(row, Settings(_env_file=None, app_env="test"))
    assert config.error == "tenant_llm_provider_invalid"
    assert config.billing_scope == "tenant" and config.api_key is None and not config.has_api_key
    assert config.base_url == ""
