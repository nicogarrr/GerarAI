"""El limite de 401 por IP no puede dejar fuera a todos los usuarios.

En produccion todo el trafico legitimo llega desde el servidor Next (las IP de
salida de Vercel), asi que AuthFailureLimitMiddleware cuenta los 401 de todos
los usuarios en la misma clave. Antes, 30 respuestas 401 en un minuto desde esa
IP (cualquiera que comparta la salida de Vercel puede provocarlas contra el
dominio publico del backend) dejaban a TODOS los usuarios en 429 durante la
ventana, aunque sus peticiones viniesen firmadas. Una firma HMAC valida prueba
el secreto compartido: pasa. Lo no firmado o mal firmado sigue cortado.
"""

import hashlib
import time
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.core.rate_limit as rate_limit_module
from app.core.auth import sign_research_identity
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


@pytest.fixture()
def client(monkeypatch):
    rate_limit_module._local_hits.clear()
    monkeypatch.setattr(rate_limit_module, "get_settings", _settings)
    app = FastAPI()
    app.add_middleware(rate_limit_module.AuthFailureLimitMiddleware, limit=3)

    @app.get("/api/private")
    def private():
        raise HTTPException(status_code=401, detail="no")

    @app.get("/api/portfolio/positions")
    def positions():
        return {"ok": True}

    yield TestClient(app)
    rate_limit_module._local_hits.clear()


def _signed_headers(path="/api/portfolio/positions", method="GET", *, secret=SECRET, ts=None):
    timestamp = str(int(time.time()) if ts is None else ts)
    nonce = uuid.uuid4().hex
    body_hash = hashlib.sha256(b"").hexdigest()
    signature = sign_research_identity(
        secret,
        tenant_id="user-b",
        user_id="user-b",
        timestamp=timestamp,
        nonce=nonce,
        method=method,
        path=path,
        body_hash=body_hash,
    )
    return {
        "X-CavaAI-User": "user-b",
        "X-CavaAI-Tenant": "user-b",
        "X-CavaAI-Timestamp": timestamp,
        "X-CavaAI-Nonce": nonce,
        "X-CavaAI-Method": method,
        "X-CavaAI-Path": path,
        "X-CavaAI-Body-Hash": body_hash,
        "X-CavaAI-Signature": signature,
    }


def _trip_limit(client):
    codes = [client.get("/api/private").status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]


def test_validly_signed_request_passes_when_shared_ip_is_over_the_401_limit(client):
    _trip_limit(client)
    response = client.get("/api/portfolio/positions", headers=_signed_headers())
    assert response.status_code == 200, response.text


def test_unsigned_and_forged_requests_are_still_cut(client):
    _trip_limit(client)
    assert client.get("/api/portfolio/positions").status_code == 429
    forged = _signed_headers(secret="f" * 32)
    assert client.get("/api/portfolio/positions", headers=forged).status_code == 429


def test_signature_for_another_path_or_stale_does_not_bypass(client):
    _trip_limit(client)
    other_path = _signed_headers(path="/api/settings/llm")
    assert client.get("/api/portfolio/positions", headers=other_path).status_code == 429
    stale = _signed_headers(ts=int(time.time()) - 10_000)
    assert client.get("/api/portfolio/positions", headers=stale).status_code == 429
    future = _signed_headers(ts=int(time.time()) + 120)
    assert client.get("/api/portfolio/positions", headers=future).status_code == 429
