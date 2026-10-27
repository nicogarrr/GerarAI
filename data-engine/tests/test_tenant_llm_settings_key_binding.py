"""La API key LLM guardada solo viaja al proveedor/URL con que se guardo."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal, init_db
from app.models import TenantLLMSettings
from tests.auth_helpers import signed_request
from tests.test_tenant_llm_settings import API_KEY, SECRET, _client, _save, _settings, _tenant


@pytest.fixture(autouse=True)
def _cleanup_llm_rows():
    """No deja filas propias: otros tests cuentan las filas de la tabla."""
    init_db()
    with SessionLocal() as db:
        before = set(
            db.scalars(
                select(TenantLLMSettings.id).execution_options(include_all_tenants=True)
            ).all()
        )
    yield
    with SessionLocal() as db:
        rows = db.scalars(
            select(TenantLLMSettings).execution_options(include_all_tenants=True)
        ).all()
        for row in rows:
            if row.id not in before:
                db.delete(row)
        db.commit()


def test_changing_provider_without_new_key_is_rejected_and_keeps_old_destination() -> None:
    init_db()
    settings = _settings()
    with SessionLocal() as db:
        tenant = _tenant(db, "llm-bind-provider")
        _save(db, tenant, settings, provider="openai", model="gpt-4.1-mini")
        with pytest.raises(ValueError, match="introduce la API key"):
            _save(db, tenant, settings, provider="groq", model="openai/gpt-oss-120b", api_key=None)
        db.rollback()
        row = db.query(TenantLLMSettings).filter_by(tenant_id=tenant.id).one()
        assert row.provider == "openai"
        assert row.api_key_ciphertext


def test_changing_custom_base_url_without_new_key_is_rejected() -> None:
    init_db()
    settings = _settings()
    with SessionLocal() as db:
        tenant = _tenant(db, "llm-bind-url")
        _save(
            db,
            tenant,
            settings,
            provider="custom",
            model="my-model",
            base_url="https://llm.mi-proveedor.example/v1",
        )
        with pytest.raises(ValueError, match="introduce la API key"):
            _save(
                db,
                tenant,
                settings,
                provider="custom",
                model="my-model",
                base_url="https://atacante.example/v1",
                api_key=None,
            )


def test_same_destination_keeps_key_and_new_key_allows_switch() -> None:
    init_db()
    settings = _settings()
    with SessionLocal() as db:
        tenant = _tenant(db, "llm-bind-ok")
        first = _save(db, tenant, settings, provider="openai", model="gpt-4.1-mini")
        ciphertext = first.api_key_ciphertext
        # Mismo proveedor, otro modelo y sin clave: se conserva la guardada.
        same = _save(db, tenant, settings, provider="openai", model="gpt-4.1", api_key=None)
        assert same.api_key_ciphertext == ciphertext
        # Cambiar de proveedor con clave nueva sí se permite.
        switched = _save(
            db, tenant, settings, provider="groq", model="openai/gpt-oss-120b", api_key="gsk-nueva-9999"
        )
        assert switched.provider == "groq"
        assert switched.api_key_last4 == "9999"
        # Borrar la clave explicitamente también permite cambiar de destino.
        cleared = _save(
            db, tenant, settings, provider="openai", model="gpt-4.1-mini", api_key=None, clear_api_key=True
        )
        assert cleared.api_key_ciphertext is None


def test_connection_test_never_sends_stored_key_to_another_url(monkeypatch) -> None:
    monkeypatch.setenv("LLM_SETTINGS_ENCRYPTION_KEY", "x" * 40)
    get_settings.cache_clear()
    client = _client(monkeypatch)
    tenant = f"llm-bind-probe-{uuid4().hex[:8]}"
    calls: list[dict] = []

    async def _fake_probe(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "status_code": 200,
            "provider": kwargs["provider"],
            "base_url": kwargs.get("base_url") or "https://api.openai.com/v1",
            "model": kwargs["model"],
            "message": "Conexion correcta.",
        }

    monkeypatch.setattr("app.api.routes.settings.probe_connection", _fake_probe)
    saved = signed_request(
        client,
        SECRET,
        tenant,
        "user-llm",
        "PUT",
        "/api/settings/llm",
        json_body={"provider": "openai", "model": "gpt-4.1-mini", "api_key": API_KEY},
    )
    assert saved.status_code == 200, saved.text

    hostile = signed_request(
        client,
        SECRET,
        tenant,
        "user-llm",
        "POST",
        "/api/settings/llm/test",
        json_body={
            "provider": "custom",
            "model": "x",
            "base_url": "https://atacante.example/v1",
        },
    )
    assert hostile.status_code == 422
    assert calls == []

    other_provider = signed_request(
        client,
        SECRET,
        tenant,
        "user-llm",
        "POST",
        "/api/settings/llm/test",
        json_body={"provider": "groq", "model": "openai/gpt-oss-120b"},
    )
    assert other_provider.status_code == 422
    assert calls == []

    same = signed_request(
        client,
        SECRET,
        tenant,
        "user-llm",
        "POST",
        "/api/settings/llm/test",
        json_body={"provider": "openai", "model": "gpt-4.1-mini"},
    )
    assert same.status_code == 200, same.text
    assert len(calls) == 1
    assert calls[0]["api_key"] == API_KEY
    assert API_KEY not in same.text
