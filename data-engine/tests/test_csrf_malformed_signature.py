"""Malformed CSRF signatures must return 403 through the complete app stack."""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import main
from app.core.csrf import generate_csrf_token, validate_csrf_token


@pytest.mark.parametrize("signature", ["é" * 64, "a" * 63 + "é", "☃"])
def test_non_ascii_signature_is_invalid(signature):
    token = f"salt.{int(time.time())}.{signature}"
    assert validate_csrf_token(token) is False


@pytest.fixture
def isolated_health_executors(monkeypatch):
    """El lifespan real cierra sus pools; no debe cerrar los del resto de la suite."""
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
        yield pools
    finally:
        for pool in pools:
            pool.shutdown(wait=True)


@pytest.mark.parametrize("header", [b"x-csrf-token", b"x-csrftoken", b"x-xsrf-token", b"cookie"])
def test_non_ascii_signature_returns_403_on_complete_app(header, isolated_health_executors):
    token = f"salt.{int(time.time())}.".encode() + b"\xe9" * 64
    value = b"csrf_token=" + token if header == b"cookie" else token
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post("/api/portfolio/add", content=b"{}", headers={header: value})
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
    # Se recorrió también el cierre real del lifespan, no un cliente sin startup.
    for pool in isolated_health_executors:
        with pytest.raises(RuntimeError, match="shutdown"):
            pool.submit(lambda: None)


def test_generated_signature_is_still_valid():
    assert validate_csrf_token(generate_csrf_token()) is True
