"""GET /api/screeners/custom-metrics y /screens con response_model.

Formas medidas contra _metric_payload y _screen_payload: serializan la fila
ORM tal cual. Servicio real sobre SQLite, sin mock.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import CustomMetricDefinition, SavedScreen, Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "screeners-lists-secret-"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"screeners-lists-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Screeners lists test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "screeners-lists-user"


def _tenant_pk(tenant_ext: str) -> int:
    db = SessionLocal()
    tenant = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.close()
    return tenant.id


def test_custom_metrics_empty(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/screeners/custom-metrics")

    assert res.status_code == 200, res.text
    assert res.json() == []


def test_custom_metrics_item_keys(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    db.add(CustomMetricDefinition(
        tenant_id=_tenant_pk(tenant), metric_key="mi_metrica", name="Mi metrica",
        formula="revenue / shares", unit="ratio", description="d", version=1, active=True,
    ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/screeners/custom-metrics")

    assert res.status_code == 200, res.text
    items = res.json()
    assert len(items) == 1
    item = items[0]
    assert set(item) == {
        "id", "metric_key", "name", "formula", "unit", "description",
        "version", "active", "metadata", "created_at",
    }
    assert item["metric_key"] == "mi_metrica"
    assert item["metadata"] == {}
    assert isinstance(item["created_at"], str)


def test_screens_empty(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/screeners/screens")

    assert res.status_code == 200, res.text
    assert res.json() == []


def test_screens_item_keys(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    db.add(SavedScreen(
        tenant_id=_tenant_pk(tenant), name="Mi pantalla", description="d",
        criteria=[{"left": "per", "operator": "<", "right": "15"}],
        ranking_formula=None, ranking_direction="desc",
        alerts_enabled=True, active=True,
    ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/screeners/screens")

    assert res.status_code == 200, res.text
    items = res.json()
    assert len(items) == 1
    item = items[0]
    assert set(item) == {
        "id", "name", "description", "criteria", "ranking_formula",
        "ranking_direction", "alerts_enabled", "active", "last_run_at", "created_at",
    }
    assert item["name"] == "Mi pantalla"
    assert item["criteria"] == [{"left": "per", "operator": "<", "right": "15"}]
    assert item["ranking_formula"] is None
    assert item["last_run_at"] is None
