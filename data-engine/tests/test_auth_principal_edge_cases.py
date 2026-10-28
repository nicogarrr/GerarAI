"""Ramas de rechazo de la firma de identidad que ningun test ejercitaba.

Cobertura (oct-2026): app/core/auth.py tenia sin probar el 503 sin secreto, el
timestamp no numerico, la firma caducada, las cabeceras ligadas a medias, la
identidad en blanco y el 503 cuando el almacen de nonces cae en produccion.
Cada una es una puerta de seguridad: si una de esas ramas devolviera 200 (o 500)
nadie se enteraria. Se prueban contra una app minima con la dependencia real.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core import auth
from app.core.replay import NonceBackendUnavailable, reset_local_nonces
from tests.auth_helpers import bound_headers, legacy_headers

SECRET = "qa-auth-edge-cases-secret-at-least-32-chars"


def _settings(**overrides) -> SimpleNamespace:
    base = dict(
        research_auth_required=True,
        research_auth_secret=SECRET,
        research_auth_max_age_seconds=300,
        research_auth_strict_binding=True,
        is_production=False,
        is_local_environment=True,
        redis_url="redis://127.0.0.1:1/0",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def make_client(monkeypatch):
    def _make(**overrides) -> TestClient:
        monkeypatch.setattr(auth, "get_settings", lambda: _settings(**overrides))
        app = FastAPI()

        @app.post("/probe")
        def probe(principal=Depends(auth.get_research_principal)):
            if principal is None:
                return {"anonymous": True}
            return {"tenant": principal.tenant_external_id, "user": principal.user_id}

        reset_local_nonces()
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _signed(tenant: str = "", user: str = "qa-user", **kw) -> dict[str, str]:
    return bound_headers(SECRET, tenant or f"t-{uuid4().hex[:8]}", user, method="POST", path="/probe", **kw)


def test_sin_cabeceras_y_auth_no_requerida_es_anonimo(make_client):
    client = make_client(research_auth_required=False)
    assert client.post("/probe").json() == {"anonymous": True}


def test_sin_cabeceras_y_auth_requerida_es_401(make_client):
    client = make_client()
    r = client.post("/probe")
    assert r.status_code == 401
    assert r.json()["detail"] == auth.MSG_IDENTITY_REQUIRED


def test_secreto_ausente_es_503_y_no_autentica(make_client):
    client = make_client(research_auth_secret="")
    r = client.post("/probe", headers=_signed())
    assert r.status_code == 503


def test_timestamp_no_numerico_es_401(make_client):
    client = make_client()
    r = client.post("/probe", headers=_signed(timestamp="ayer"))
    assert r.status_code == 401
    assert r.json()["detail"] == auth.MSG_INVALID_TIMESTAMP


def test_timestamp_futuro_es_401_aunque_la_firma_sea_valida(make_client):
    client = make_client()
    r = client.post("/probe", headers=_signed(timestamp=str(int(time.time()) + 120)))
    assert r.status_code == 401
    assert r.json()["detail"] == auth.MSG_INVALID_TIMESTAMP


def test_firma_caducada_es_401(make_client):
    client = make_client(research_auth_max_age_seconds=60)
    r = client.post("/probe", headers=_signed(timestamp=str(int(time.time()) - 61)))
    assert r.status_code == 401
    assert r.json()["detail"] == auth.MSG_EXPIRED


@pytest.mark.parametrize("missing", ["X-CavaAI-Nonce", "X-CavaAI-Method", "X-CavaAI-Path", "X-CavaAI-Body-Hash"])
def test_cabeceras_ligadas_a_medias_son_401(make_client, missing):
    """Quitar UNA de las cuatro cabeceras ligadas no puede degradar a firma legacy."""
    client = make_client(research_auth_strict_binding=False)
    headers = _signed()
    headers.pop(missing)
    r = client.post("/probe", headers=headers)
    assert r.status_code == 401
    assert r.json()["detail"] == auth.MSG_INVALID_SIGNATURE


def test_firma_legacy_rechazada_con_binding_estricto(make_client):
    client = make_client(research_auth_strict_binding=True)
    r = client.post("/probe", headers=legacy_headers(SECRET, "t-legacy", "u-legacy"))
    assert r.status_code == 401
    assert r.json()["detail"] == auth.MSG_BOUND_SIGNATURE_REQUIRED


def test_firma_legacy_aceptada_solo_en_modo_leniente(make_client):
    client = make_client(research_auth_strict_binding=False)
    r = client.post("/probe", headers=legacy_headers(SECRET, "t-legacy", "u-legacy"))
    assert r.status_code == 200
    assert r.json() == {"tenant": "t-legacy", "user": "u-legacy"}


def test_firma_de_otra_ruta_es_401(make_client):
    client = make_client()
    headers = bound_headers(SECRET, "t-x", "u-x", method="POST", path="/otra")
    r = client.post("/probe", headers=headers)
    assert r.status_code == 401
    assert r.json()["detail"] == auth.MSG_REQUEST_MISMATCH


def test_cuerpo_alterado_es_401(make_client):
    client = make_client()
    headers = _signed(body=b'{"qty": 1}')
    r = client.post("/probe", headers=headers, content=b'{"qty": 1000}')
    assert r.status_code == 401
    assert r.json()["detail"] == auth.MSG_REQUEST_MISMATCH


@pytest.mark.parametrize(("tenant", "user"), [("   ", "u-ok"), ("t-ok", "   ")])
def test_identidad_en_blanco_es_401_aunque_este_bien_firmada(make_client, tenant, user):
    client = make_client()
    r = client.post("/probe", headers=bound_headers(SECRET, tenant, user, method="POST", path="/probe"))
    assert r.status_code == 401
    assert r.json()["detail"] == auth.MSG_INVALID_IDENTITY


def test_identidad_con_espacios_se_normaliza(make_client):
    client = make_client()
    r = client.post("/probe", headers=bound_headers(SECRET, " t-pad ", " u-pad ", method="POST", path="/probe"))
    assert r.status_code == 200
    assert r.json() == {"tenant": "t-pad", "user": "u-pad"}


def test_replay_del_mismo_nonce_es_401(make_client):
    client = make_client()
    headers = _signed()
    assert client.post("/probe", headers=headers).status_code == 200
    r = client.post("/probe", headers=headers)
    assert r.status_code == 401
    assert r.json()["detail"] == auth.MSG_REPLAYED


def test_almacen_de_nonces_caido_en_produccion_es_503(make_client, monkeypatch):
    """Produccion falla cerrado: sin Redis no se acepta la firma (ni se degrada)."""
    client = make_client(is_production=True, is_local_environment=False, app_env="production")

    async def down(*_a, **_k):
        raise NonceBackendUnavailable("redis down")

    monkeypatch.setattr(auth, "consume_nonce", down)
    r = client.post("/probe", headers=_signed())
    assert r.status_code == 503
    assert r.json()["detail"] == "Authentication backend unavailable"


def test_signature_payload_rechaza_campos_ligados_a_medias():
    with pytest.raises(ValueError):
        auth.signature_payload(tenant_id="t", user_id="u", timestamp="1", nonce="n")
