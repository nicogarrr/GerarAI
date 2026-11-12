"""Pruebas de presencia de cabeceras de seguridad HTTP (VAL-SEC-006).

Fulfills: VAL-SEC-006
Expected Behavior:
- All HTTP responses include X-Frame-Options, X-Content-Type-Options, etc.
- Headers are present across root, health, and API endpoints
- Security headers configured via middleware
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture(scope="module")
def client():
    # The real lifespan shuts these down. Own this module's pools rather
    # than poisoning readiness tests that run later in the same process.
    names = ("_HEALTH_REQUIRED_EXECUTOR", "_HEALTH_PROBE_EXECUTOR", "_HEALTH_LLM_EXECUTOR")
    originals = {name: getattr(main, name) for name in names}
    owned = []
    with pytest.MonkeyPatch.context() as patch:
        for name, workers in zip(names, (2, 4, 1)):
            pool = ThreadPoolExecutor(max_workers=workers)
            owned.append(pool)
            patch.setattr(main, name, pool)
        try:
            with TestClient(main.app) as test_client:
                yield test_client
            # Observe the real lifespan shutdown before fallback cleanup.
            assert all(pool._shutdown for pool in owned)
        finally:
            for pool in owned:
                pool.shutdown(wait=True)
    # Preserve real shutdown coverage AND prove parent-process pools survive.
    assert all(pool._shutdown for pool in owned)
    for name, original in originals.items():
        assert getattr(main, name) is original
        assert original.submit(lambda: "alive").result(timeout=2) == "alive"


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

