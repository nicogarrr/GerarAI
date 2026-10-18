"""Route tests for POST /api/workflows/ThesisShadowComparisonWorkflow/run.

The shadow graph thread is namespaced per tenant: the route requires tenant
context (403, same guard as ThesisApprovalWorkflow) and passes the real
tenant to the service instead of the old shared "shadow" default. The
response run_id comes from the recorded run payload, not from a racy
"latest run" re-query.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant, WorkflowRun
from tests.auth_helpers import auth_settings, signed_request

SECRET = "shadow-route-test-secret-with-at-least-32-chars"


def _seed_company(ticker: str) -> None:
    db = SessionLocal()
    try:
        if db.scalar(select(Company).where(Company.ticker == ticker)) is None:
            db.add(
                Company(
                    ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
                    sector="Tech", industry="Tech", company_type="holding",
                    valuation_model="unassigned", special_sources=[],
                    special_risks=[], factor_tags=[],
                )
            )
            db.commit()
    finally:
        db.close()


def _tenant_pk(external_id: str) -> int:
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.external_id == external_id))
        assert tenant is not None
        return tenant.id
    finally:
        db.close()


def _shadow_runs(ticker: str) -> list[WorkflowRun]:
    """Runs del shadow para ``ticker`` (la BD de sesion es compartida)."""
    db = SessionLocal()
    try:
        runs = list(
            db.scalars(
                select(WorkflowRun).where(
                    WorkflowRun.workflow_name == "ThesisShadowComparisonWorkflow"
                )
            ).all()
        )
        return [run for run in runs if (run.input_payload or {}).get("ticker") == ticker]
    finally:
        db.close()


def test_shadow_run_requires_tenant_context():
    """Sin tenant en la sesion el shadow no corre: 403, no namespace global."""
    init_db()
    _seed_company("SHDNOAUTH")
    client = TestClient(main.app)
    # Settings por defecto de tests: research_auth_required=False, sesion
    # anonima sin db.info["tenant_id"].
    response = client.post(
        "/api/workflows/ThesisShadowComparisonWorkflow/run",
        json={"ticker": "SHDNOAUTH"},
    )
    assert response.status_code == 403
    assert _shadow_runs("SHDNOAUTH") == []


def test_shadow_run_is_namespaced_per_tenant(monkeypatch):
    """Con identidad firmada, el thread usa thesis:{tenant}:... y el run_id
    de la respuesta es el del run grabado (no una re-consulta con carrera)."""
    init_db()
    _seed_company("SHDTEN")
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET, app_env="local"),
    )
    tenant_external = "shadow-tenant-a"
    client = TestClient(main.app)
    response = signed_request(
        client, SECRET, tenant_external, "user-shadow", "POST",
        "/api/workflows/ThesisShadowComparisonWorkflow/run",
        json_body={"ticker": "SHDTEN"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    tenant_pk = _tenant_pk(tenant_external)

    thread_id = body["result"]["thread_id"]
    assert thread_id.startswith(f"thesis:{tenant_pk}:")
    assert not thread_id.startswith("thesis:shadow:")

    runs = _shadow_runs("SHDTEN")
    assert len(runs) == 1
    assert runs[0].tenant_id == tenant_pk
    assert body["run_id"] == runs[0].id
    assert body["result"]["run_id"] == runs[0].id


def test_shadow_replay_returns_original_run_id(monkeypatch):
    """Re-entrega idempotente: mismo run_id, sin ejecutar dos veces."""
    init_db()
    _seed_company("SHDREPLAY")
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET, app_env="local"),
    )
    client = TestClient(main.app)
    headers = {"Idempotency-Key": "shadow-replay-1"}
    first = signed_request(
        client, SECRET, "shadow-tenant-r", "user-shadow", "POST",
        "/api/workflows/ThesisShadowComparisonWorkflow/run",
        json_body={"ticker": "SHDREPLAY"}, headers=headers,
    )
    assert first.status_code == 200, first.text
    second = signed_request(
        client, SECRET, "shadow-tenant-r", "user-shadow", "POST",
        "/api/workflows/ThesisShadowComparisonWorkflow/run",
        json_body={"ticker": "SHDREPLAY"}, headers=headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["idempotent_replay"] is True
    assert second.json()["run_id"] == first.json()["run_id"]
    assert len(_shadow_runs("SHDREPLAY")) == 1
