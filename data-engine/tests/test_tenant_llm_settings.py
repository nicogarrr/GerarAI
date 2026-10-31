"""Ajustes LLM por tenant: cifrado, aislamiento, factorias y endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core import auth as auth_module
from app.core import database as database_module
from app.core.config import Settings, get_settings
from app.core.database import SessionLocal, init_db
from app.core.llm_settings_crypto import (
    LLMSettingsCryptoError,
    decrypt_api_key,
    encrypt_api_key,
    encryption_available,
)
from app.llm.chat_provider import (
    create_background_llm_provider,
    create_chat_llm_provider,
)
from app.llm.factory import create_llm_provider
from app.llm.tenant_config import TenantLLMConfig, tenant_llm_config_scope
from app.models import BudgetUsage, Tenant, TenantLLMSettings
from app.services.budget import BudgetController
from app.services.tenant_llm_settings_service import (
    TenantLLMUpdate,
    config_from_row,
    probe_connection,
    save_tenant_settings,
)
from tests.auth_helpers import auth_settings, signed_request

SECRET = "tenant-llm-test-secret-with-at-least-32-characters"
API_KEY = "sk-tenant-secret-key-1234"


def _settings(**extra) -> Settings:
    base = dict(
        _env_file=None,
        app_env="test",
        research_auth_secret="local-fallback-secret-with-at-least-32-bytes",
        llm_settings_encryption_key="explicit-encryption-key-with-32-bytes!",
        opencode_go_api_key="platform-key-not-for-tenants",
    )
    base.update(extra)
    return Settings(**base)


def _tenant(db, name: str) -> Tenant:
    tenant = Tenant(external_id=f"{name}-{uuid4().hex[:8]}", name=name)
    db.add(tenant)
    db.flush()
    return tenant


def _save(db, tenant: Tenant, settings: Settings, **overrides):
    db.info["tenant_id"] = tenant.id
    update = {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "api_key": API_KEY,
    }
    update.update(overrides)
    row = save_tenant_settings(db, TenantLLMUpdate(**update), settings)
    db.commit()
    return row


def test_api_key_roundtrip_and_no_plaintext_storage() -> None:
    settings = _settings()
    ciphertext = encrypt_api_key(API_KEY, settings)
    assert API_KEY not in ciphertext
    assert decrypt_api_key(ciphertext, settings) == API_KEY
    assert encryption_available(settings)

    without_key = _settings().model_copy(
        update={"app_env": "production", "llm_settings_encryption_key": None}
    )
    assert not encryption_available(without_key)
    with pytest.raises(LLMSettingsCryptoError):
        encrypt_api_key(API_KEY, without_key)


def test_two_tenants_keep_distinct_configs_and_rows() -> None:
    init_db()
    settings = _settings()
    with SessionLocal() as db:
        tenant_a = _tenant(db, "llm-a")
        tenant_b = _tenant(db, "llm-b")
        _save(
            db,
            tenant_a,
            settings,
            provider="openai",
            model="gpt-4.1-mini",
            api_key="sk-tenant-a-1111",
        )
        _save(
            db,
            tenant_b,
            settings,
            provider="groq",
            model="openai/gpt-oss-120b",
            api_key="sk-tenant-b-2222",
        )
        db.info.pop("tenant_id", None)
        rows = db.scalars(
            select(TenantLLMSettings).execution_options(include_all_tenants=True)
        ).all()
        assert len(rows) == 2
        assert len({row.api_key_ciphertext for row in rows}) == 2
        assert all("sk-tenant" not in (row.api_key_ciphertext or "") for row in rows)
        assert {row.api_key_last4 for row in rows} == {"1111", "2222"}


def test_factories_resolve_each_tenant_and_never_fall_back() -> None:
    init_db()
    settings = _settings()
    with SessionLocal() as db:
        tenant_a = _tenant(db, "llm-factory-a")
        tenant_b = _tenant(db, "llm-factory-b")
        row_a = _save(
            db,
            tenant_a,
            settings,
            provider="openai",
            model="gpt-4.1-mini",
            api_key="sk-tenant-a-1111",
        )
        row_b = _save(
            db,
            tenant_b,
            settings,
            provider="groq",
            model="openai/gpt-oss-120b",
            api_key="sk-tenant-b-2222",
        )
        config_a = config_from_row(row_a, settings)
        config_b = config_from_row(row_b, settings)
        assert config_a.provider == "openai"
        assert config_b.provider == "groq"

        with tenant_llm_config_scope(config_a):
            provider_a = create_llm_provider(settings)
            assert provider_a.name == "openai"
            assert provider_a.billing_scope == "tenant"
            assert provider_a._api_key == "sk-tenant-a-1111"  # noqa: SLF001
        with tenant_llm_config_scope(config_b):
            provider_b = create_llm_provider(settings)
            assert provider_b.name == "groq"
            assert provider_b._api_key == "sk-tenant-b-2222"  # noqa: SLF001

        with tenant_llm_config_scope(config_a):
            assert create_chat_llm_provider(settings).name == "openai"
            assert create_background_llm_provider(settings).name == "openai"


def test_no_row_keeps_platform_and_corrupt_row_fails_closed() -> None:
    init_db()
    settings = _settings()
    with tenant_llm_config_scope(None):
        provider = create_llm_provider(settings)
        assert provider.name == "opencode-go"

    corrupt = TenantLLMConfig(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4.1-mini",
        api_key=None,
        error="tenant_llm_settings_corrupt",
    )
    with tenant_llm_config_scope(corrupt):
        provider = create_llm_provider(settings)
        assert provider.name == "disabled"
        assert provider.reason == "tenant_llm_settings_corrupt"  # type: ignore[attr-defined]

    missing = TenantLLMConfig(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4.1-mini",
        api_key=None,
    )
    with tenant_llm_config_scope(missing):
        assert create_llm_provider(settings).name == "disabled"
        assert create_chat_llm_provider(settings).name == "disabled"
        assert create_background_llm_provider(settings).name == "disabled"


def test_tenant_key_bypasses_eur_caps_and_records_zero_cost() -> None:
    init_db()
    settings = _settings()
    with SessionLocal() as db:
        tenant = _tenant(db, "llm-budget")
        row = _save(db, tenant, settings)
        config = config_from_row(row, settings)
        db.info["tenant_id"] = tenant.id
        budget = BudgetController()
        with tenant_llm_config_scope(None):
            assert not budget.can_spend(db, 999.0)
        with tenant_llm_config_scope(config):
            assert budget.can_spend(db, 999.0)
            budget.record(db, "gpt-4.1-mini", "test", 12.5, 100)
        cost = db.scalar(
            select(BudgetUsage.cost_eur).where(BudgetUsage.tenant_id == tenant.id)
        )
        assert cost == 0


class _FakeResponse:
    def __init__(self, status_code: int, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"data": [{"id": "gpt-4.1-mini"}]}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeClient:
    calls: list[tuple[str, dict[str, str]]] = []

    def __init__(self, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str]):
        type(self).calls.append((url, headers))
        return _FakeResponse(200)


@pytest.mark.parametrize(
    ("provider", "base_url", "expected"),
    [
        ("openai", None, "https://api.openai.com/v1/models"),
        ("custom", "https://llm.example.test/v1", "https://llm.example.test/v1/models"),
    ],
)
def test_probe_connection_uses_five_second_client_and_never_leaks_key(
    monkeypatch, provider, base_url, expected
) -> None:
    _FakeClient.calls.clear()
    monkeypatch.setattr(
        "app.services.tenant_llm_settings_service.httpx.AsyncClient", _FakeClient
    )
    import asyncio

    result = asyncio.run(
        probe_connection(
            provider=provider,
            base_url=base_url,
            api_key=API_KEY,
            model="gpt-4.1-mini",
        )
    )
    assert result["ok"] is True
    assert _FakeClient.calls[0][0] == expected
    assert API_KEY not in str(result)


def _probe_with(monkeypatch, payload, model="gpt-4.1-mini"):
    """probe_connection con la lista /models inyectada (sin red)."""
    _FakeClient.calls.clear()

    class _Client(_FakeClient):
        async def get(self, url, headers):
            type(self).calls.append((url, headers))
            return _FakeResponse(200, payload)

    monkeypatch.setattr(
        "app.services.tenant_llm_settings_service.httpx.AsyncClient", _Client
    )
    import asyncio

    return asyncio.run(
        probe_connection(provider="openai", base_url=None, api_key=API_KEY, model=model)
    )


def test_probe_rechaza_modelo_inventado_aunque_la_conexion_responda(monkeypatch) -> None:
    """Hallazgo front (medido en prod): model="modelo-inventado-123" decia
    "Conexion correcta". Ahora el modelo debe aparecer en /models."""
    result = _probe_with(monkeypatch, {"data": [{"id": "gpt-4.1-mini"}]}, model="modelo-inventado-123")
    assert result["ok"] is False
    assert "modelo-inventado-123" in result["message"]
    assert "no existe" in result["message"]
    assert API_KEY not in str(result)


def test_probe_acepta_modelo_presente_en_la_lista(monkeypatch) -> None:
    result = _probe_with(monkeypatch, {"data": [{"id": "otro"}, {"id": "gpt-4.1-mini"}]})
    assert result["ok"] is True
    assert result["message"] == "Conexion correcta."


def test_probe_falla_honesto_si_la_lista_no_es_legible(monkeypatch) -> None:
    for payload in (ValueError("no json"), {"error": "nope"}, {"data": "texto"}):
        result = _probe_with(monkeypatch, payload)
        assert result["ok"] is False
        assert "no se pudo verificar el modelo" in result["message"]


def _client(monkeypatch, *, required: bool = True) -> TestClient:
    init_db()
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET, app_env="local", required=required),
    )
    monkeypatch.setattr(database_module, "settings", database_module.settings.model_copy(update={"research_auth_required": required}))
    return TestClient(main.app)


def test_endpoint_401_without_identity(monkeypatch) -> None:
    client = _client(monkeypatch, required=True)
    assert client.get("/api/settings/llm").status_code == 401


def test_endpoint_put_get_does_not_leak_key(monkeypatch) -> None:
    monkeypatch.setenv("LLM_SETTINGS_ENCRYPTION_KEY", "x" * 40)
    get_settings.cache_clear()
    client = _client(monkeypatch)
    tenant = f"llm-api-{uuid4().hex[:8]}"
    payload = {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "api_key": API_KEY,
        "enabled": True,
    }
    response = signed_request(
        client,
        SECRET,
        tenant,
        "user-llm",
        "PUT",
        "/api/settings/llm",
        json_body=payload,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "tenant"
    assert body["provider"] == "openai"
    assert body["api_key_configured"] is True
    assert body["api_key_last4"] == "1234"
    assert API_KEY not in response.text

    listed = signed_request(
        client, SECRET, tenant, "user-llm", "GET", "/api/settings/llm"
    )
    assert listed.status_code == 200
    assert listed.json()["model"] == "gpt-4.1-mini"
    assert API_KEY not in listed.text

    # El ContextVar de la dependencia llega a create_llm_provider en la
    # vista agregada de /api/settings.
    overall = signed_request(client, SECRET, tenant, "user-llm", "GET", "/api/settings")
    assert overall.status_code == 200
    assert overall.json()["llm"]["provider"] == "openai"
    assert overall.json()["llm"]["model"] == "gpt-4.1-mini"
    assert API_KEY not in overall.text


def test_endpoint_rejects_custom_private_url_and_missing_encryption(monkeypatch) -> None:
    monkeypatch.delenv("LLM_SETTINGS_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()
    client = _client(monkeypatch)
    tenant = f"llm-api-invalid-{uuid4().hex[:8]}"

    invalid = signed_request(
        client,
        SECRET,
        tenant,
        "user-llm",
        "PUT",
        "/api/settings/llm",
        json_body={
            "provider": "custom",
            "model": "my-model",
            "base_url": "http://127.0.0.1:8080/v1",
            "api_key": API_KEY,
        },
    )
    assert invalid.status_code == 503

    no_key = signed_request(
        client,
        SECRET,
        tenant,
        "user-llm",
        "PUT",
        "/api/settings/llm",
        json_body={
            "provider": "custom",
            "model": "my-model",
            "base_url": "https://127.0.0.1:8080/v1",
        },
    )
    assert no_key.status_code == 422
    assert "privada" in no_key.json()["detail"] or "reservada" in no_key.json()["detail"]


def test_endpoint_put_rejects_private_custom_url_422(monkeypatch) -> None:
    monkeypatch.setenv("LLM_SETTINGS_ENCRYPTION_KEY", "x" * 40)
    get_settings.cache_clear()
    client = _client(monkeypatch)
    tenant = f"llm-api-ssrf-{uuid4().hex[:8]}"
    response = signed_request(
        client,
        SECRET,
        tenant,
        "user-llm",
        "PUT",
        "/api/settings/llm",
        json_body={
            "provider": "custom",
            "model": "my-model",
            "base_url": "https://10.0.0.5/v1",
        },
    )
    assert response.status_code == 422
    assert "privada" in response.json()["detail"] or "reservada" in response.json()["detail"]


def test_endpoint_test_requires_key_422(monkeypatch) -> None:
    monkeypatch.setenv("LLM_SETTINGS_ENCRYPTION_KEY", "x" * 40)
    get_settings.cache_clear()
    client = _client(monkeypatch)
    tenant = f"llm-api-test-{uuid4().hex[:8]}"
    response = signed_request(
        client,
        SECRET,
        tenant,
        "user-llm",
        "POST",
        "/api/settings/llm/test",
        json_body={"provider": "openai", "model": "gpt-4.1-mini"},
    )
    assert response.status_code == 422
    assert "API key" in response.json()["detail"]


def test_endpoint_test_returns_probe_result_without_key(monkeypatch) -> None:
    monkeypatch.setenv("LLM_SETTINGS_ENCRYPTION_KEY", "x" * 40)
    get_settings.cache_clear()
    client = _client(monkeypatch)
    tenant = f"llm-api-probe-{uuid4().hex[:8]}"

    async def _fake_probe(**_kwargs):
        return {
            "ok": True,
            "status_code": 200,
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1-mini",
            "message": "Conexion correcta.",
        }

    monkeypatch.setattr(
        "app.api.routes.settings.probe_connection", _fake_probe
    )
    response = signed_request(
        client,
        SECRET,
        tenant,
        "user-llm",
        "POST",
        "/api/settings/llm/test",
        json_body={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "api_key": API_KEY,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert API_KEY not in response.text
