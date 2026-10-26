"""Malformed signatures must fail as auth errors, never as server errors."""

import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core import auth
from app.core.replay import reset_local_nonces
from tests.auth_helpers import bound_headers

SECRET = "qa-signature-boundary-at-least-32-characters"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(
        research_auth_required=True,
        research_auth_secret=SECRET,
        research_auth_max_age_seconds=300,
        research_auth_strict_binding=True,
        is_production=False,
        is_local_environment=True,
    ))
    app = FastAPI()

    @app.get("/probe")
    def probe(principal=Depends(auth.get_research_principal)):
        return {"tenant": principal.tenant_external_id}

    reset_local_nonces()
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("signature", [b"\xe9" * 64, b"g" * 64, b"a" * 63, b"a" * 65])
def test_malformed_signature_returns_401_without_consuming_nonce(client, signature):
    headers = bound_headers(SECRET, "qa-tenant", "qa-user", method="GET", path="/probe")
    bad = {key.encode(): value.encode() for key, value in headers.items()}
    bad[b"X-CavaAI-Signature"] = signature
    response = client.get("/probe", headers=bad)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid Research OS identity signature"
    # A forged request cannot consume the authentic request's one-use nonce.
    assert client.get("/probe", headers=headers).status_code == 200
    assert client.get("/probe", headers=headers).status_code == 401


def test_valid_signature_still_authenticates(client):
    headers = bound_headers(
        SECRET, f"qa-{uuid4().hex}", "qa-user", method="GET", path="/probe",
        timestamp=str(int(time.time())),
    )
    response = client.get("/probe", headers=headers)
    assert response.status_code == 200
    assert response.json()["tenant"] == headers["X-CavaAI-Tenant"]
