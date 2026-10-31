"""Rutas de escritura de riesgo sin test directo (lote 4): snapshots.

- POST /api/portfolio/snapshots/capture: congela valoracion de cartera
  (dinero); cable ruta->servicio con tenant firmado.
- POST /api/propicks/snapshots: congela el mes del embudo; mes vacio ->
  409 honesto (no se congela nada), con ganadores -> 201.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "risky-write-routes-b4-test-secret-at-least-32-chars"


def _client_with_tenant(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"risky-b4-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Risky b4"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext


def test_portfolio_snapshot_capture_runs_with_signed_tenant(monkeypatch):
    import app.api.routes.portfolio as portfolio_routes
    from app.models.entities import PortfolioDailySnapshot

    seen = []

    class _FakeService:
        def capture(self, db, *, as_of=None, source=None):
            seen.append((db.info.get("tenant_id"), as_of, source))
            snap = PortfolioDailySnapshot(
                tenant_id=db.info["tenant_id"],
                portfolio_id=1,
                snapshot_date=as_of or date.today(),
                base_currency="EUR",
                total_value_base=Decimal("1234.56"),
                positions_value_base=Decimal("1000"),
                cash_value_base=Decimal("234.56"),
                net_external_flow_base=Decimal("0"),
                pricing_coverage=1.0, source="manual_capture",
            )
            db.add(snap)
            db.flush()
            return snap

    monkeypatch.setattr(portfolio_routes, "PortfolioSnapshotService", _FakeService)
    client, tenant = _client_with_tenant(monkeypatch)
    res = signed_request(client, SECRET, tenant, "u1", "POST", "/api/portfolio/snapshots/capture")
    assert res.status_code == 200, res.text
    assert float(res.json()["total_value_base"]) == 1234.56
    assert seen and seen[0][0] is not None and seen[0][2] == "manual_capture"


def test_propicks_freeze_empty_month_is_honest_409(monkeypatch):
    import app.services.propicks_snapshot_service as snap

    monkeypatch.setattr(snap, "freeze_monthly_snapshot", lambda db: None)
    client, tenant = _client_with_tenant(monkeypatch)
    res = signed_request(client, SECRET, tenant, "u1", "POST", "/api/propicks/snapshots")
    assert res.status_code == 409, res.text
    assert "no se congela" in res.text


def test_propicks_freeze_with_passers_returns_201(monkeypatch):
    import app.services.propicks_snapshot_service as snap
    from types import SimpleNamespace

    row = SimpleNamespace(month="2026-10", as_of="2026-10-31", passed_count=3)
    monkeypatch.setattr(snap, "freeze_monthly_snapshot", lambda db: row)
    client, tenant = _client_with_tenant(monkeypatch)
    res = signed_request(client, SECRET, tenant, "u1", "POST", "/api/propicks/snapshots")
    assert res.status_code == 201, res.text
    assert res.json()["passed_count"] == 3
