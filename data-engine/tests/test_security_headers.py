"""Pruebas de presencia de cabeceras de seguridad HTTP (VAL-SEC-006).

Fulfills: VAL-SEC-006
Expected Behavior:
- All HTTP responses include X-Frame-Options, X-Content-Type-Options, etc.
- Headers are present across root, health, and API endpoints
- Security headers configured via middleware
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/health",
        "/api/csrf-token",
    ],
)
def test_security_headers_present_on_routes(client, path: str):
    """VAL-SEC-006: Comprueba que las cabeceras de seguridad esten presentes en las rutas."""
    res = client.get(path)
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") in {"DENY", "SAMEORIGIN"}
    assert res.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "camera=()" in res.headers.get("permissions-policy", "")

