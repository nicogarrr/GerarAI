"""GET /api/watchlist con response_model.

Forma medida contra la ruta y tracked_analysis.tracked_statuses: item con 6
claves siempre (id, symbol, company, created_at, updated_at, analysis).
analysis null sin workflow; con workflow lleva status/as_of/thesis_status y
OMITE missing_inputs salvo estado insufficient_data con empresa conocida:
exclude_unset + test de ausencia. Servicio real sobre SQLite, sin mock.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant, WatchItem, WorkflowRun
from app.services.thesis_job_service import WORKFLOW_NAME
from tests.auth_helpers import auth_settings, signed_request

SECRET = "watchlist-list-secret-"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"watchlist-list-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Watchlist list test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "watchlist-list-user"


def _tenant_pk(tenant_ext: str) -> int:
    db = SessionLocal()
    tenant = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.close()
    return tenant.id


def test_watchlist_empty(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist")

    assert res.status_code == 200, res.text
    assert res.json() == []


def test_watchlist_item_without_analysis(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    db.add(WatchItem(tenant_id=_tenant_pk(tenant), symbol="ACME", company="Acme Corp"))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist")

    assert res.status_code == 200, res.text
    items = res.json()
    assert len(items) == 1
    item = items[0]
    # 6 claves siempre; analysis null sin workflow run.
    assert set(item) == {"id", "symbol", "company", "created_at", "updated_at", "analysis"}
    assert item["symbol"] == "ACME"
    assert item["company"] == "Acme Corp"
    assert item["analysis"] is None


def test_watchlist_item_with_analysis_omits_missing_inputs(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    tenant_pk = _tenant_pk(tenant)
    db = SessionLocal()
    db.add(WatchItem(tenant_id=tenant_pk, symbol="ACME"))
    db.add(WorkflowRun(
        tenant_id=tenant_pk,
        workflow_name=WORKFLOW_NAME,
        status="succeeded",
        input_payload={"ticker": "ACME"},
        result_payload={"status": "ok"},
    ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist")

    assert res.status_code == 200, res.text
    analysis = res.json()[0]["analysis"]
    # Estado presente: thesis_status siempre; missing_inputs AUSENTE
    # (no es insufficient_data): exclude_unset, nunca null anadido.
    assert set(analysis) == {"status", "as_of", "thesis_status"}
    assert analysis["status"] == "succeeded"
    assert analysis["thesis_status"] == "ok"
