"""GET /api/ownership/managers* con response_model: el wire es el contrato exacto.

Estas rutas devolvian schema free-form y una deriva real (status "snapshot" y
7 campos null en la rama snapshot) llego al front sin que nadie la viera. Los
tests ejercitan la respuesta HTTP real con los payloads de cada rama del
servicio: si response_model recorta un campo o rechaza un null legitimo, el
test falla.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.services.manager_holding_ingestion_service import (
    ManagerHoldingIngestionService,
)
from tests.auth_helpers import auth_settings, signed_request

SECRET = "ownership-read-routes-test-secret-at-least-32-chars"
CIK = "0001067983"  # Berkshire Hathaway Inc (REVIEWED_MANAGERS)


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"ownership-read-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Ownership read routes test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "ownership-read-user"


def _snapshot_payload() -> dict:
    """Forma real de _snapshot_holdings_payload: lo que el snapshot no tiene va en None."""
    return {
        "cik": CIK,
        "manager": "Berkshire Hathaway Inc",
        "status": "snapshot",
        "verification": "snapshot_unverified",
        "report_date": "2026-06-30",
        "coverage": "snapshot",
        "holdings": [
            {
                "accession_number": None,
                "is_amendment": False,
                "name_of_issuer": "APPLE INC",
                "name_of_issuer_filed": "APPLE INC",
                "title_of_class": "COM",
                "cusip": "037833100",
                "value_usd_thousands": 80000000.0,
                "shares": 400000000.0,
                "share_type": "SH",
                "put_call": None,
                "investment_discretion": "SOLE",
                "filing_url": None,
            }
        ],
        "errors": [],
        "limitations": ["cobertura parcial de prueba"],
        "transport": "edgartools-snapshot",
        "snapshot_synced_at": "2026-10-30T04:00:00+00:00",
        "provenance": {
            "source": "SEC EDGAR 13F snapshot",
            "source_kind": "sec_edgar",
            "source_url": None,
            "fetched_at": "2026-10-30T04:00:00+00:00",
            "coverage": "snapshot",
            "note": None,
        },
    }


def test_list_managers_wire_shape(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    res = signed_request(client, SECRET, tenant, user, "GET", "/api/ownership/managers")
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body["managers"], list) and body["managers"]
    assert all(set(m) == {"cik", "name"} for m in body["managers"])
    assert {m["cik"] for m in body["managers"]} == {CIK} | {
        m["cik"] for m in body["managers"] if m["cik"] != CIK
    }
    assert any(m["cik"] == CIK and m["name"] == "Berkshire Hathaway Inc" for m in body["managers"])
    assert isinstance(body["limitations"], list)
    assert all(isinstance(item, str) for item in body["limitations"])


def test_holdings_snapshot_branch_keeps_nulls_and_extras(monkeypatch) -> None:
    """La rama snapshot emite nulls y campos extra: response_model debe pasarlos intactos."""
    client, tenant, user = _client(monkeypatch)
    monkeypatch.setattr(
        "app.services.investor_autosync.maybe_autosync_holdings", lambda db: None
    )
    monkeypatch.setattr(
        ManagerHoldingIngestionService,
        "latest_holdings",
        lambda self, db, *, cik: _snapshot_payload(),
    )
    res = signed_request(
        client, SECRET, tenant, user, "GET", f"/api/ownership/managers/{CIK}/holdings"
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "snapshot"
    assert body["verification"] == "snapshot_unverified"
    row = body["holdings"][0]
    assert row["filing_url"] is None
    assert row["accession_number"] is None
    assert row["put_call"] is None
    # Campos de la rama snapshot que no deben desaparecer del wire:
    assert body["transport"] == "edgartools-snapshot"
    assert body["snapshot_synced_at"] == "2026-10-30T04:00:00+00:00"
    assert body["errors"] == []
    assert body["provenance"]["source_kind"] == "sec_edgar"


def test_holdings_verified_branch_ok(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    monkeypatch.setattr(
        "app.services.investor_autosync.maybe_autosync_holdings", lambda db: None
    )
    payload = _snapshot_payload()
    payload.update(
        status="ok",
        verification="verified",
        coverage="ok",
        errors=None,
        transport=None,
        snapshot_synced_at=None,
    )
    payload["holdings"][0].update(
        accession_number="0001067983-26-000001",
        filing_url="https://www.sec.gov/Archives/edgar/data/1067983/000106798326000001/xslForm13F_X02/form13fInfoTable.xml",
    )
    monkeypatch.setattr(
        ManagerHoldingIngestionService,
        "latest_holdings",
        lambda self, db, *, cik: payload,
    )
    res = signed_request(
        client, SECRET, tenant, user, "GET", f"/api/ownership/managers/{CIK}/holdings"
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ok"
    assert body["verification"] == "verified"
    assert body["holdings"][0]["filing_url"].startswith("https://www.sec.gov/")
    assert body["errors"] is None


def test_changes_insufficient_history_keeps_nulls(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    payload = {
        "status": "insufficient_history",
        "cik": CIK,
        "manager": None,
        "detail": "solo hay un periodo 13F ingerido",
        "latest_report": None,
        "previous_report": None,
        "compared_accessions": None,
        "changes": [],
        "limitations": None,
        "provenance": None,
    }
    monkeypatch.setattr(
        ManagerHoldingIngestionService, "changes", lambda self, db, *, cik: payload
    )
    res = signed_request(
        client, SECRET, tenant, user, "GET", f"/api/ownership/managers/{CIK}/changes"
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "insufficient_history"
    assert body["latest_report"] is None
    assert body["compared_accessions"] is None
    assert body["provenance"] is None
    assert body["changes"] == []


def test_changes_ok_rows_wire_shape(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    payload = {
        "status": "ok",
        "cik": CIK,
        "manager": "Berkshire Hathaway Inc",
        "detail": None,
        "latest_report": "2026-06-30",
        "previous_report": "2026-03-31",
        "compared_accessions": {
            "latest": "0001067983-26-000002",
            "previous": "0001067983-26-000001",
            "rule": "amendment_mas_reciente",
        },
        "changes": [
            {
                "change": "increased",
                "name_of_issuer": "APPLE INC",
                "title_of_class": "COM",
                "cusip": "037833100",
                "put_call": None,
                "shares_latest": 400000000.0,
                "shares_previous": 300000000.0,
                "value_usd_thousands_latest": 80000000.0,
                "value_usd_thousands_previous": 55000000.0,
            }
        ],
        "limitations": ["cobertura parcial de prueba"],
        "provenance": {
            "source": "SEC EDGAR 13F",
            "source_kind": "sec_edgar",
            "source_url": None,
            "fetched_at": "2026-10-30T04:00:00+00:00",
            "coverage": "ok",
            "note": None,
        },
    }
    monkeypatch.setattr(
        ManagerHoldingIngestionService, "changes", lambda self, db, *, cik: payload
    )
    res = signed_request(
        client, SECRET, tenant, user, "GET", f"/api/ownership/managers/{CIK}/changes"
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ok"
    row = body["changes"][0]
    assert row["change"] == "increased"
    assert row["put_call"] is None
    assert body["compared_accessions"]["latest"] == "0001067983-26-000002"
