"""El relay de Telegram (bot Asistenta) debe atravesar el CSRFMiddleware real.

Regresion: ``CSRFMiddleware`` exige token CSRF o cabeceras X-CavaAI-* en todo
metodo mutante. ``POST /api/telegram/link-proof`` no lleva ninguna de las dos
(su auth es la firma X-Asistenta-*, con su propio secreto y ventana), asi que
en la app real TODA prueba de vinculacion del bot recibia 403 antes de llegar
a la ruta y la vinculacion de Telegram no funcionaba. Los tests existentes
montaban ``relay_router`` en una FastAPI pelada, sin el middleware, y no lo
veian. Estos tests ejercitan la app completa de ``main``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.api.routes import telegram_link as routes
from app.core.database import init_db
from main import app

RELAY_PATH = "/api/telegram/link-proof"
SECRET = "test-only-relay-secret-0123456789abcdef"


def _relay_body(token: str = "t" * 43) -> bytes:
    return json.dumps(
        {
            "token": token,
            "chat_id": "12345",
            "telegram_user_id": "12345",
            "chat_type": "private",
        }
    ).encode()


def _relay_headers(body: bytes, secret: str = SECRET, signature: str | None = None) -> dict[str, str]:
    stamp = str(int(time.time()))
    if signature is None:
        signature = hmac.new(
            secret.encode(), stamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Asistenta-Timestamp": stamp,
        "X-Asistenta-Signature": signature,
    }


@pytest.fixture
def client(monkeypatch):
    init_db()
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: type("S", (), {"telegram_link_secret": SECRET})(),
    )
    return TestClient(app, raise_server_exceptions=False)


def test_relay_valid_signature_reaches_route_not_csrf(client: TestClient):
    """Con firma de bot valida la peticion llega a la ruta: 409 (token
    desconocido) y no el 403 del middleware CSRF."""
    body = _relay_body()
    response = client.post(RELAY_PATH, content=body, headers=_relay_headers(body))
    assert response.status_code == 409
    assert response.json()["detail"] == "Código de vinculación usado o caducado"


def test_relay_invalid_signature_is_401_not_csrf_403(client: TestClient):
    """Firma de bot invalida: la ruta responde 401; nunca el 403 de CSRF."""
    body = _relay_body()
    response = client.post(
        RELAY_PATH, content=body, headers=_relay_headers(body, signature="0" * 64)
    )
    assert response.status_code == 401


def test_relay_without_signature_is_401_not_csrf_403(client: TestClient):
    """Sin cabeceras de bot: la ruta responde 401; la exencion no abre la ruta."""
    body = _relay_body()
    response = client.post(
        RELAY_PATH, content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 401


def test_other_mutating_routes_still_require_csrf(client: TestClient):
    """La exencion exacta no relaja el resto: otro POST sin token sigue en 403."""
    response = client.post("/api/portfolio/add", json={})
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


def test_similar_prefix_is_not_exempt(client: TestClient):
    """La exencion es de ruta exacta: un sufijo parecido no se cuela por ella."""
    response = client.post(RELAY_PATH + "-extra", json={})
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_other_methods_on_relay_path_still_require_csrf(client: TestClient, method: str):
    """La exencion es SOLO para POST: PUT/PATCH/DELETE en la misma ruta siguen
    exigiendo CSRF (403 del middleware, no el 405 del routing)."""
    body = _relay_body()
    response = client.request(
        method.upper(), RELAY_PATH, content=body, headers=_relay_headers(body)
    )
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
