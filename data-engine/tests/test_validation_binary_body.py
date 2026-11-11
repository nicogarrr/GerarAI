"""Rejected binary bodies must produce a serializable 422, not a UnicodeDecodeError."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.requests import Request

import main
from app.core import auth as auth_module
from app.core.database import init_db
from tests.auth_helpers import auth_settings, bound_headers

SECRET = "binary-validation-test-secret-at-least-32-characters"


@pytest.fixture()
def client(monkeypatch):
    init_db()
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET, app_env="test"),
    )
    pools = []
    for name, workers in (
        ("_HEALTH_REQUIRED_EXECUTOR", 2),
        ("_HEALTH_PROBE_EXECUTOR", 4),
        ("_HEALTH_LLM_EXECUTOR", 1),
    ):
        pool = ThreadPoolExecutor(max_workers=workers)
        pools.append(pool)
        monkeypatch.setattr(main, name, pool)
    try:
        with TestClient(main.app, raise_server_exceptions=False) as client:
            yield client
    finally:
        for pool in pools:
            pool.shutdown(wait=True)


@pytest.mark.parametrize("path,method", [("/api/watchlist", "POST"), ("/api/settings/dca", "PUT")])
@pytest.mark.parametrize("body", [b"\xff", b"\x80\x81", b"{\xff}", b"plain text", "año".encode()])
def test_rejected_binary_body_returns_422(client, path, method, body):
    suffix = uuid4().hex[:8]
    headers = bound_headers(SECRET, f"binary-{suffix}", f"user-{suffix}", method=method, path=path, body=body)
    headers["Content-Type"] = "application/octet-stream"
    response = client.request(method, path, content=body, headers=headers)
    assert response.status_code == 422, response.text
    error = response.json()["detail"][0]
    assert error["loc"] == ["body"]
    assert error["type"] == "model_attributes_type"
    assert error["input"] == body.decode("utf-8", errors="replace")
    assert isinstance(error["msg"], str)


def test_binary_body_still_requires_valid_signature(client):
    body = b"\xff"
    headers = bound_headers(
        SECRET, "binary-unsigned", "user", method="POST", path="/api/watchlist", body=body
    )
    headers["Content-Type"] = "application/octet-stream"
    headers["X-CavaAI-Signature"] = "invalid"
    response = client.post("/api/watchlist", content=body, headers=headers)
    assert response.status_code == 401


def test_nested_bytes_and_non_finite_inputs_remain_serializable():
    exc = RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", "field"),
                "msg": "invalid input",
                "input": {"nested": [b"\xff", (b"valid", float("inf"), float("nan"))]},
            }
        ]
    )
    request = Request({"type": "http", "method": "POST", "path": "/"})
    response = asyncio.run(main.request_validation_error_handler(request, exc))
    import json

    assert response.status_code == 422
    error = json.loads(response.body)["detail"][0]
    assert error["loc"] == ["body", "field"]
    assert error["input"] == {"nested": ["\ufffd", ["valid", "inf", "nan"]]}
