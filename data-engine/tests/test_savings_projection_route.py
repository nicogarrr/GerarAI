"""GET /api/plan/savings-projection con response_model: servicio real, las 3 ramas.

El servicio es computacion pura + una lectura ORM: no hace falta mock para
cubrir las ramas no_plan / currency_missing / ok, y asi el contrato se valida
contra el payload real, no contra una forma recordada.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.models.entities import InvestmentPlan
from tests.auth_helpers import auth_settings, signed_request

SECRET = "savings-projection-route-test-secret-32-chars"


def _client(monkeypatch) -> tuple[TestClient, str, str, int]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"savings-{uuid4().hex[:8]}"
    db = SessionLocal()
    tenant = Tenant(external_id=tenant_ext, name="Savings projection test")
    db.add(tenant)
    db.commit()
    tenant_id = tenant.id
    db.close()
    return TestClient(main.app), tenant_ext, "savings-user", tenant_id


def test_no_plan_branch_with_real_service(monkeypatch) -> None:
    client, tenant, user, _ = _client(monkeypatch)
    res = signed_request(client, SECRET, tenant, user, "GET", "/api/plan/savings-projection")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "no_plan"
    assert body["plan_exists"] is False
    assert body["plan_id"] is None
    assert body["monthly_contribution"] is None
    assert body["currency"] is None
    assert body["horizon_years"] is None
    assert body["scenarios"] == []
    assert body["assumptions"]


def test_currency_missing_branch_preview_without_currency(monkeypatch) -> None:
    client, tenant, user, _ = _client(monkeypatch)
    res = signed_request(
        client, SECRET, tenant, user, "GET", "/api/plan/savings-projection",
        params={"monthly": "100", "years": "10"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "currency_missing"
    assert body["preview"] is True
    assert body["scenarios"] == []


def test_ok_branch_preview_scenarios_and_null_net_dividend(monkeypatch) -> None:
    client, tenant, user, _ = _client(monkeypatch)
    res = signed_request(
        client, SECRET, tenant, user, "GET", "/api/plan/savings-projection",
        params={"monthly": "100", "years": "10", "currency": "EUR", "annual_return": "0.07"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ok"
    assert body["currency"] == "EUR"
    assert len(body["scenarios"]) == 1
    scenario = body["scenarios"][0]
    assert scenario["years"] == 10
    assert scenario["contributed"] == 12000.0
    assert scenario["terminal_value"] > scenario["contributed"]
    assert scenario["net_dividend"] is None  # campo reservado: siempre null hoy


def test_ok_branch_from_real_plan_row(monkeypatch) -> None:
    """Sin query params lee el plan del tenant: plan_exists y plan_id reales."""
    client, tenant, user, tenant_id = _client(monkeypatch)
    db = SessionLocal()
    db.add(
        InvestmentPlan(
            tenant_id=tenant_id,
            monthly_contribution=250,
            monthly_contribution_currency="EUR",
            start_date=date(2026, 1, 1),
            horizon_years=20,
            target_allocations=[],
        )
    )
    db.commit()
    db.close()
    res = signed_request(client, SECRET, tenant, user, "GET", "/api/plan/savings-projection")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ok"
    assert body["plan_exists"] is True
    assert isinstance(body["plan_id"], int)
    assert body["monthly_contribution"] == 250.0
    assert body["currency"] == "EUR"
    assert body["horizon_years"] == 20
    assert len(body["scenarios"]) >= 1
