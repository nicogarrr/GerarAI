"""GET /api/thesis/{ticker}/audio/status, /jobs/{run_id} y /jobs con response_model.

audio/status: state y key siempre; generated_at SOLO cuando el mp3 esta listo
(status_info lo omite en cualquier otro estado): exclude_unset + ausencia.
El unico doble es httpx en la frontera de red del servicio TTS (precedente
_NoProvider). jobs: 13 claves medidas en job_payload, huecos a null.
Servicio real sobre SQLite.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant, ThesisVersion, WorkflowRun
from app.services import thesis_audio_service
from app.services.thesis_job_service import WORKFLOW_NAME
from tests.auth_helpers import auth_settings, signed_request

SECRET = "thesis-jobs-audio-secret-"

JOB_KEYS = {
    "id", "workflow_name", "status", "ticker", "force", "phases", "current_phase",
    "total_phases", "result", "error_class", "error_message", "attempt",
    "created_at", "started_at", "finished_at",
}


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"thesis-jobs-audio-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Thesis jobs audio test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "thesis-jobs-audio-user"


def _tenant_pk(tenant_ext: str) -> int:
    db = SessionLocal()
    tenant = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.close()
    return tenant.id


def test_audio_status_missing_without_published(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/thesis/NOPE/audio/status")

    assert res.status_code == 200, res.text
    payload = res.json()
    # Sin tesis publicada: missing (no 404); generated_at AUSENTE siempre aqui.
    assert set(payload) == {"state", "key"}
    assert payload["state"] == "missing"
    assert payload["key"] is None


def test_audio_status_ready_includes_generated_at(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    tenant_pk = _tenant_pk(tenant)
    db = SessionLocal()
    company = Company(ticker="AJBS", name="Acme", exchange="NYSE", currency="USD",
                      company_type="operating", valuation_model="unassigned")
    db.add(company)
    db.flush()
    db.add(ThesisVersion(
        tenant_id=tenant_pk, company_id=company.id, version=1,
        status="published", thesis_markdown="t", executive_summary="e", rating="buy",
    ))
    db.commit()
    db.close()

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"state": "ready", "generated_at": "2026-10-31T10:00:00Z"}

    monkeypatch.setattr(thesis_audio_service.httpx, "get", lambda *a, **k: _Resp())

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/thesis/AJBS/audio/status")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert set(payload) == {"state", "key", "generated_at"}
    assert payload["state"] == "ready"
    assert payload["generated_at"] == "2026-10-31T10:00:00Z"
    assert payload["key"]


def test_job_status_404_unknown(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/thesis/jobs/999999")

    assert res.status_code == 404


def test_job_status_13_keys(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    run = WorkflowRun(
        tenant_id=_tenant_pk(tenant), workflow_name=WORKFLOW_NAME, status="running",
        input_payload={"ticker": "AJBS"}, idempotency_key=f"k-{uuid4().hex[:8]}",
    )
    db.add(run)
    db.commit()
    run_id = run.id
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", f"/api/thesis/jobs/{run_id}")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert set(payload) == JOB_KEYS
    assert payload["ticker"] == "AJBS"
    assert payload["status"] == "running"
    assert payload["phases"] == []
    assert payload["result"] is None
    assert payload["error_class"] is None


def test_latest_job_none(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/thesis/jobs", params={"ticker": "AJBS"})

    assert res.status_code == 200, res.text
    assert res.json() == {"job": None}
