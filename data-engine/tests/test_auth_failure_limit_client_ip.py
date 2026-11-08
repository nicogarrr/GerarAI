"""AuthFailureLimitMiddleware se keyed por la IP real del cliente, no por el peer.

Detras de Caddy el peer del socket es siempre la IP privada del proxy: con esa
clave TODO el trafico compartia un unico cubo de 401s, y 30 respuestas 401 en
un minuto en toda la instalacion (sesiones caducadas de cualquier usuario,
sondas, bots) cortaban en 429 a todo el trafico no firmado durante la ventana.

La ultima entrada de X-Forwarded-For solo se acepta de un proxy de la
allowlist ``forwarded_allow_ips`` (la misma que arranca uvicorn con
--forwarded-allow-ips): un cliente directo en la red interna no puede rotar
su cubo falsificando la cabecera.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.core.rate_limit as rate_limit_module
from app.core.config import Settings

SECRET = "0123456789abcdef0123456789abcdef"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        rate_limit_enabled=True,
        research_auth_secret=SECRET,
        redis_url="redis://127.0.0.1:6399/15",
    )


def _app(monkeypatch, limit: int = 1) -> FastAPI:
    monkeypatch.setattr(rate_limit_module, "get_settings", _settings)
    app = FastAPI()
    app.add_middleware(rate_limit_module.AuthFailureLimitMiddleware, limit=limit)

    @app.get("/api/private")
    def private():
        raise HTTPException(status_code=401, detail="no")

    return app


@pytest.fixture(autouse=True)
def _clean_local_hits():
    rate_limit_module._local_hits.clear()
    yield
    rate_limit_module._local_hits.clear()


def test_bucket_keyed_by_forwarded_ip_behind_trusted_proxy(monkeypatch):
    """Peer en la allowlist (172.16.0.0/12, la de uvicorn en prod): cada IP
    real tiene su cubo y agotar el de una no corta a otra."""
    client = TestClient(_app(monkeypatch), client=("172.18.0.2", 1234))
    ip_a = {"X-Forwarded-For": "203.0.113.9"}
    ip_b = {"X-Forwarded-For": "203.0.113.10"}

    assert client.get("/api/private", headers=ip_a).status_code == 401
    # Cubo de A agotado (limit=1): su siguiente peticion no firmada -> 429.
    assert client.get("/api/private", headers=ip_a).status_code == 429
    # El cubo de B es independiente: sigue llegando al 401 de la ruta.
    assert client.get("/api/private", headers=ip_b).status_code == 401
    assert client.get("/api/private", headers=ip_b).status_code == 429


def test_untrusted_private_peer_cannot_rotate_bucket_with_xff(monkeypatch):
    """Peer privado FUERA de la allowlist (cliente directo en red interna):
    rotar X-Forwarded-For no cambia su cubo — sigue contando por su IP."""
    client = TestClient(_app(monkeypatch), client=("192.168.1.77", 1234))

    assert client.get("/api/private").status_code == 401
    for fake in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
        assert (
            client.get("/api/private", headers={"X-Forwarded-For": fake}).status_code
            == 429
        )


def test_public_peer_ignores_forwarded_for(monkeypatch):
    """Con peer publico (uvicorn --proxy-headers ya dejo la IP real en el
    scope, o acceso directo) la cabecera XFF no cambia el cubo."""
    # OJO: 198.51.100.0/24 y 203.0.113.0/24 son rangos de documentacion y
    # ipaddress los marca como privados; un peer "publico" de verdad para el
    # test necesita una IP enrutable (8.8.8.8).
    client = TestClient(_app(monkeypatch), client=("8.8.8.8", 1234))

    assert client.get("/api/private").status_code == 401
    # Mismo peer, XFF distinta: sigue siendo el cubo del peer -> 429.
    assert (
        client.get("/api/private", headers={"X-Forwarded-For": "1.1.1.1"}).status_code
        == 429
    )


def test_allowlist_honours_explicit_entries(monkeypatch):
    """La allowlist es configurable: una IP o CIDR declarada si aporta XFF."""
    def settings_with_allowlist() -> Settings:
        return Settings(
            _env_file=None,
            app_env="test",
            rate_limit_enabled=True,
            research_auth_secret=SECRET,
            redis_url="redis://127.0.0.1:6399/15",
            forwarded_allow_ips="192.168.1.77",
        )

    monkeypatch.setattr(rate_limit_module, "get_settings", settings_with_allowlist)
    app = FastAPI()
    app.add_middleware(rate_limit_module.AuthFailureLimitMiddleware, limit=1)

    @app.get("/api/private")
    def private():
        raise HTTPException(status_code=401, detail="no")

    client = TestClient(app, client=("192.168.1.77", 1234))
    ip_a = {"X-Forwarded-For": "203.0.113.9"}
    ip_b = {"X-Forwarded-For": "203.0.113.10"}
    assert client.get("/api/private", headers=ip_a).status_code == 401
    assert client.get("/api/private", headers=ip_a).status_code == 429
    assert client.get("/api/private", headers=ip_b).status_code == 401
