"""Malformed CSRF signatures must return 403 through the complete app stack."""

import time

import pytest
from fastapi.testclient import TestClient

from app.core.csrf import generate_csrf_token, validate_csrf_token
from main import app


@pytest.mark.parametrize("signature", ["é" * 64, "a" * 63 + "é", "☃"])
def test_non_ascii_signature_is_invalid(signature):
    token = f"salt.{int(time.time())}.{signature}"
    assert validate_csrf_token(token) is False


@pytest.mark.parametrize("header", [b"x-csrf-token", b"x-csrftoken", b"x-xsrf-token", b"cookie"])
def test_non_ascii_signature_returns_403_on_complete_app(header):
    token = f"salt.{int(time.time())}.".encode() + b"\xe9" * 64
    value = b"csrf_token=" + token if header == b"cookie" else token
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/portfolio/add", content=b"{}", headers={header: value})
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


def test_generated_signature_is_still_valid():
    assert validate_csrf_token(generate_csrf_token()) is True
