"""El tope de body grande exige una firma valida, no solo la cabecera.

RawBodyMiddleware deja 10-16MB a las peticiones firmadas y 1MB al resto. La
comprobacion era la mera presencia de ``X-CavaAI-Signature``: cualquiera podia
mandar ``X-CavaAI-Signature: x`` contra el backend publico y hacerle
bufferizar 10-16MB por peticion antes del 401.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.core import config
from app.core.raw_body import RawBodyMiddleware
from tests.auth_helpers import bound_headers

SECRET = "raw-body-cap-secret-with-at-least-32-characters"
BODY = b"x" * 2048


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RawBodyMiddleware, max_unsigned_body_bytes=1024)

    @app.post("/echo")
    async def echo(request: Request):
        return JSONResponse({"len": len(await request.body())})

    return app


def _settings(secret):
    return SimpleNamespace(research_auth_secret=secret, research_auth_max_age_seconds=300)


def test_forged_signature_header_keeps_the_small_cap(monkeypatch):
    monkeypatch.setattr(config, "get_settings", lambda: _settings(SECRET))
    client = TestClient(_app())
    forged = {
        "X-CavaAI-Signature": "a" * 64,
        "X-CavaAI-User": "u",
        "X-CavaAI-Tenant": "t",
        "X-CavaAI-Timestamp": "1",
    }
    assert client.post("/echo", content=BODY, headers=forged).status_code == 413
    assert client.post("/echo", content=BODY, headers={"X-CavaAI-Signature": "x"}).status_code == 413


def test_valid_signature_gets_the_large_cap(monkeypatch):
    monkeypatch.setattr(config, "get_settings", lambda: _settings(SECRET))
    client = TestClient(_app())
    headers = bound_headers(SECRET, "t", "u", method="POST", path="/echo", body=BODY)
    response = client.post("/echo", content=BODY, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"len": 2048}


def test_without_secret_presence_still_lifts_the_cap(monkeypatch):
    monkeypatch.setattr(config, "get_settings", lambda: _settings(None))
    client = TestClient(_app())
    assert client.post("/echo", content=BODY, headers={"X-CavaAI-Signature": "x"}).status_code == 200
    assert client.post("/echo", content=BODY).status_code == 413
