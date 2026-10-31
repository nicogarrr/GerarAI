"""POST /api/workflows/{name}/run hardening (audit F-workflows 2/3/4).

- DailyResearchWorkflow validates news_items BEFORE begin_run: an invalid
  payload is a 422 and no workflow_runs row is left hanging in "running".
- EarningsWorkflow params go through a pydantic model: no silent coercions
  (bool("false") was True), invalid values are 422 before opening the run,
  and the envelope records the normalized values it actually executes.
- run_workflow is a sync endpoint: FastAPI runs it in the threadpool
  instead of blocking the event loop with sync DB/service work.
"""

import inspect
from types import SimpleNamespace

from sqlalchemy import select

import main
from app.api.routes import workflows as workflows_route
from app.core.database import SessionLocal, init_db
from app.models import Company, WorkflowRun
from tests.auth_helpers import csrf_client

client = csrf_client(main.app)


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


def _runs(workflow_name: str) -> list[WorkflowRun]:
    db = SessionLocal()
    try:
        return list(
            db.scalars(
                select(WorkflowRun).where(WorkflowRun.workflow_name == workflow_name)
            ).all()
        )
    finally:
        db.close()


def test_daily_research_invalid_items_422_without_open_run():
    """news_items invalido: 422 y ningun run colgado (antes: 500 + running)."""
    init_db()
    before = len(_runs("DailyResearchWorkflow"))
    response = client.post(
        "/api/workflows/DailyResearchWorkflow/run",
        json={"params": {"news_items": [{"title": "ab"}]}},
    )
    assert response.status_code == 422, response.text
    assert len(_runs("DailyResearchWorkflow")) == before


def test_earnings_invalid_params_422_without_open_run():
    """fiscal_year no entero: 422 antes de abrir el run."""
    init_db()
    _seed_company("EARNV")
    before = len(_runs("EarningsWorkflow"))
    response = client.post(
        "/api/workflows/EarningsWorkflow/run",
        json={"ticker": "EARNV", "params": {"fiscal_year": "abc"}},
    )
    assert response.status_code == 422, response.text
    assert len(_runs("EarningsWorkflow")) == before


def test_earnings_params_normalized_not_silently_coerced(monkeypatch):
    """force_new_thesis="false" (string) ejecuta False, no True; y el
    envelope graba los params normalizados que realmente corrieron."""
    init_db()
    _seed_company("EARNB")
    captured: dict = {}

    def fake_run(self, db, company, **kwargs):  # noqa: ARG001
        captured.update(kwargs)
        return SimpleNamespace(
            status="completed", error=None, id=1, thesis_change_id=None,
            document_ids=kwargs["document_ids"], extracted_metrics=[],
            guidance_changes=[],
        )

    monkeypatch.setattr(
        "app.services.earnings_service.EarningsWorkflowService.run", fake_run
    )
    response = client.post(
        "/api/workflows/EarningsWorkflow/run",
        json={
            "ticker": "EARNB",
            "params": {"force_new_thesis": "false", "fiscal_year": 2024},
        },
    )
    assert response.status_code == 200, response.text
    assert captured["force_new_thesis"] is False
    assert captured["fiscal_year"] == 2024
    runs = [r for r in _runs("EarningsWorkflow")
            if (r.input_payload or {}).get("ticker") == "EARNB"]
    assert len(runs) == 1
    recorded = runs[0].input_payload["params"]
    assert recorded["force_new_thesis"] is False
    assert recorded["fiscal_year"] == 2024


def test_run_endpoint_is_sync_not_event_loop_blocking():
    """Regresion: el handler no puede volver a ser una corutina."""
    assert not inspect.iscoroutinefunction(workflows_route.run_workflow)


def test_red_team_maf_branch_runs_off_the_loop(monkeypatch):
    """La rama MAF (corutina) funciona desde el endpoint sync via puente."""
    init_db()
    _seed_company("REDTM")

    def fake_run(self, db, company):  # noqa: ARG001
        return SimpleNamespace(status="completed", id=7, score=55, findings=[])

    monkeypatch.setattr("app.services.red_team_service.RedTeamService.run", fake_run)
    response = client.post(
        "/api/workflows/RedTeamWorkflow/run",
        json={"ticker": "REDTM"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["result"]["red_team_run_id"] == 7
