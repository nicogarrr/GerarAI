"""Rutas de escritura de riesgo sin test directo (auditoria rutas x tests).

Lote 1: invalidacion de caches (POST /api/cache/invalidate/*) y sync 13F
sincrono (POST /api/ownership/managers/sync). Patron identico a
test_ownership_sync_async: binding estricto + signed_request + dobles.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "risky-write-routes-test-secret-at-least-32-chars"


def _client_with_tenant(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"risky-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Risky write routes test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext


def test_cache_invalidate_market_data_calls_cache_layer(monkeypatch):
    import app.api.routes.cache as cache_routes

    calls = []
    monkeypatch.setattr(
        cache_routes, "invalidate_market_data_cache", lambda: calls.append("market")
    )
    client, tenant = _client_with_tenant(monkeypatch)
    res = signed_request(client, SECRET, tenant, "u1", "POST", "/api/cache/invalidate/market-data")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ok"
    assert calls == ["market"]


def test_cache_invalidate_portfolio_is_tenant_scoped(monkeypatch):
    import app.api.routes.cache as cache_routes

    seen = []
    monkeypatch.setattr(
        cache_routes,
        "invalidate_portfolio_cache",
        lambda db: seen.append(db.info.get("tenant_id")),
    )
    client, tenant = _client_with_tenant(monkeypatch)
    res = signed_request(client, SECRET, tenant, "u1", "POST", "/api/cache/invalidate/portfolio")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ok"
    # La invalidacion corre con el tenant del firmante, nunca global por error.
    assert seen and seen[0] is not None


def test_cache_invalidate_dca_and_all(monkeypatch):
    import app.api.routes.cache as cache_routes

    calls = []
    monkeypatch.setattr(cache_routes, "invalidate_dca_cache", lambda db: calls.append("dca"))
    monkeypatch.setattr(cache_routes, "invalidate_market_data_cache", lambda: calls.append("market"))
    monkeypatch.setattr(cache_routes, "invalidate_portfolio_cache", lambda db: calls.append("portfolio"))
    monkeypatch.setattr(cache_routes, "reset_cache_stats", lambda: calls.append("reset"))
    client, tenant = _client_with_tenant(monkeypatch)

    res = signed_request(client, SECRET, tenant, "u1", "POST", "/api/cache/invalidate/dca")
    assert res.status_code == 200, res.text
    assert calls == ["dca"]

    res = signed_request(client, SECRET, tenant, "u1", "POST", "/api/cache/invalidate/all")
    assert res.status_code == 200, res.text
    assert "market" in calls and "portfolio" in calls and "dca" in calls


def test_ownership_managers_sync_runs_service_for_signed_tenant(monkeypatch):
    import app.api.routes.ownership as ownership_routes

    calls = []

    class _FakeService:
        def sync_all(self, db):
            calls.append(("all", db.info.get("tenant_id")))
            return {"status": "ok", "synced": 0}

    monkeypatch.setattr(ownership_routes, "ManagerHoldingIngestionService", _FakeService)
    client, tenant = _client_with_tenant(monkeypatch)
    res = signed_request(client, SECRET, tenant, "u1", "POST", "/api/ownership/managers/sync")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ok"
    assert calls and calls[0][0] == "all" and calls[0][1] is not None
