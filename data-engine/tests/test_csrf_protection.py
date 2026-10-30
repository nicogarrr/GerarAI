"""Tests for CSRF protection on state-changing endpoints.

Fulfills: VAL-SEC-001 (CSRF protection on state-changing endpoints).
Assertion: POST /api/portfolio/add without CSRF token returns 403 Forbidden.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.csrf import generate_csrf_token, validate_csrf_token
from app.core.database import init_db
from main import app


@pytest.fixture
def client():
    init_db()
    return TestClient(app)


def test_post_portfolio_add_without_csrf_returns_403(client: TestClient):
    """VAL-SEC-001: POST /api/portfolio/add without CSRF token returns 403 Forbidden."""
    payload = {
        "ticker": "AAPL",
        "action": "buy",
        "quantity": "10",
        "price": "150.00",
        "trade_date": "2026-10-30",
        "currency": "USD",
    }
    response = client.post("/api/portfolio/add", json=payload)
    assert response.status_code == 403
    data = response.json()
    assert "detail" in data
    assert "CSRF" in data["detail"]


def test_get_csrf_token_endpoint(client: TestClient):
    """GET /api/csrf-token returns a valid CSRF token."""
    response = client.get("/api/csrf-token")
    assert response.status_code == 200
    data = response.json()
    assert "csrf_token" in data
    token = data["csrf_token"]
    assert validate_csrf_token(token) is True


def test_post_with_invalid_csrf_token_returns_403(client: TestClient):
    """POST with corrupted/forged CSRF token returns 403 Forbidden."""
    payload = {
        "ticker": "AAPL",
        "action": "buy",
        "quantity": "10",
        "price": "150.00",
        "trade_date": "2026-10-30",
        "currency": "USD",
    }
    response = client.post(
        "/api/portfolio/add",
        json=payload,
        headers={"X-CSRF-Token": "bad_salt.1234567.fake_signature_hash"},
    )
    assert response.status_code == 403


def test_post_with_expired_csrf_token_returns_403(client: TestClient):
    """POST with expired CSRF token returns 403 Forbidden."""
    # Token issued 2 days ago
    with patch("time.time", return_value=time.time() - 200000):
        old_token = generate_csrf_token()

    payload = {
        "ticker": "AAPL",
        "action": "buy",
        "quantity": "10",
        "price": "150.00",
        "trade_date": "2026-10-30",
        "currency": "USD",
    }
    response = client.post(
        "/api/portfolio/add",
        json=payload,
        headers={"X-CSRF-Token": old_token},
    )
    assert response.status_code == 403


def test_post_with_valid_csrf_token_passes_csrf_filter(client: TestClient):
    """POST with valid CSRF token passes the CSRF gate (status != 403)."""
    token = generate_csrf_token()
    payload = {
        "ticker": "AAPL",
        "action": "buy",
        "quantity": "10",
        "price": "150.00",
        "trade_date": "2026-10-30",
        "currency": "USD",
    }
    response = client.post(
        "/api/portfolio/add",
        json=payload,
        headers={"X-CSRF-Token": token},
    )
    # The CSRF check must pass (so it is not 403)
    assert response.status_code != 403


def test_safe_get_methods_do_not_require_csrf(client: TestClient):
    """GET requests are safe methods and do not require CSRF token."""
    response = client.get("/api/health")
    assert response.status_code == 200

