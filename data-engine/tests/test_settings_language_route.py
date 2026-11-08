"""Ruta /api/settings/language (app/api/routes/language.py).

Hueco de cobertura: la preferencia de idioma de generacion del tenant no
tenia ningun test de ruta (solo app/core/i18n.py, el plumbing de peticion,
lo tiene test_request_language.py). Aqui se prueba el par GET/PUT contra la
API firmada: identidad, normalizacion, persistencia en Tenant.metadata_,
rechazo de idiomas no soportados y la honestidad de despliegue
(generation_enabled refleja I18N_GENERATION_ENABLED).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core import auth as auth_module
from app.core.config import get_settings
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "settings-language-test-secret-at-least-32ch"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    yield TestClient(main.app)


def _tenant_ext() -> str:
    return f"lang-{uuid4().hex[:8]}"


def _stored_language(external_id: str):
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.external_id == external_id))
        return None if tenant is None else (tenant.metadata_ or {}).get("language")
    finally:
        db.close()


def test_get_language_requires_signed_identity(client):
    res = client.get("/api/settings/language")
    assert res.status_code == 401


def test_put_language_requires_signed_identity(client):
    # Sin firma el middleware CSRF rechaza antes que la auth (403, no 401).
    res = client.put("/api/settings/language", json={"language": "en"})
    assert res.status_code == 403


def test_get_language_defaults_to_spanish(client):
    tenant = _tenant_ext()
    res = signed_request(client, SECRET, tenant, "u1", "GET", "/api/settings/language")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["language"] == "es"
    assert body["supported"] == ["es", "en"]
    # Sin I18N_GENERATION_ENABLED la eleccion se guarda pero no cambia la
    # generacion: la respuesta lo dice, no lo esconde.
    assert body["generation_enabled"] is False


def test_put_language_persists_and_get_reads_it_back(client):
    tenant = _tenant_ext()
    res = signed_request(
        client, SECRET, tenant, "u1", "PUT", "/api/settings/language",
        json_body={"language": "en"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["language"] == "en"
    assert _stored_language(tenant) == "en"

    res = signed_request(client, SECRET, tenant, "u1", "GET", "/api/settings/language")
    assert res.status_code == 200, res.text
    assert res.json()["language"] == "en"


def test_put_language_normalizes_case_region_and_underscore(client):
    tenant = _tenant_ext()
    res = signed_request(
        client, SECRET, tenant, "u1", "PUT", "/api/settings/language",
        json_body={"language": " EN_us "},
    )
    assert res.status_code == 200, res.text
    assert res.json()["language"] == "en"
    assert _stored_language(tenant) == "en"


def test_put_language_rejects_unsupported_language(client):
    tenant = _tenant_ext()
    res = signed_request(
        client, SECRET, tenant, "u1", "PUT", "/api/settings/language",
        json_body={"language": "fr"},
    )
    assert res.status_code == 422, res.text
    # Con el flag apagado el detalle sale en espanol (ui_error) y nombra lo pedido.
    assert "Idioma no soportado" in res.json()["detail"]
    assert "fr" in res.json()["detail"]
    # No se guarda nada: la preferencia anterior (ninguna) sigue igual.
    assert _stored_language(tenant) is None


def test_put_language_rejects_extra_fields(client):
    tenant = _tenant_ext()
    res = signed_request(
        client, SECRET, tenant, "u1", "PUT", "/api/settings/language",
        json_body={"language": "en", "admin": True},
    )
    assert res.status_code == 422, res.text


def test_language_preference_is_per_tenant(client):
    tenant_a, tenant_b = _tenant_ext(), _tenant_ext()
    res = signed_request(
        client, SECRET, tenant_a, "u1", "PUT", "/api/settings/language",
        json_body={"language": "en"},
    )
    assert res.status_code == 200, res.text
    res = signed_request(client, SECRET, tenant_b, "u1", "GET", "/api/settings/language")
    assert res.status_code == 200, res.text
    assert res.json()["language"] == "es"


def test_generation_enabled_reflects_the_flag(client, monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    tenant = _tenant_ext()
    res = signed_request(client, SECRET, tenant, "u1", "GET", "/api/settings/language")
    assert res.status_code == 200, res.text
    assert res.json()["generation_enabled"] is True
