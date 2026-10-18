"""Stage 6b: shadow comparison service tests."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, ThesisVersion, WorkflowRun
from app.services.thesis_job_service import THESIS_PHASES
from app.services.thesis_shadow_service import (
    PHASE_TO_NODE,
    WORKFLOW_NAME,
    ThesisShadowService,
)
from app.workflows.thesis_graph import THESIS_GRAPH_NODES


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str = "AAPL") -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_unknown_company(db):
    assert ThesisShadowService().run(db, ticker="NOPE", tenant_external_id="suite")["status"] == "unknown_company"


def test_shadow_runs_graph_and_records_comparison(db):
    _company(db)
    db.add(ThesisVersion(company_id=1, version=1, status="published", thesis_markdown="# t", executive_summary="s"))
    db.commit()
    result = ThesisShadowService().run(db, ticker="AAPL", tenant_external_id="suite")
    execution = result["graph_execution"]
    assert execution["nodes_in_order"] is True
    assert execution["completed_nodes"] == list(THESIS_GRAPH_NODES)
    assert execution["final_status"] == "published"
    assert execution["idempotent_retry"] is True
    assert execution["approval_interrupt"]["interrupted_at_gate"] is True
    assert execution["retry_added_nodes"] == []
    assert result["phase_mapping"]["complete"] is True
    assert result["status_semantics"]["classic_latest_version"] == {
        "version": 1,
        "status": "published",
    }
    assert result["shadow_only"] is True
    # Thread namespacetado por el tenant explicito, nunca un "shadow" global.
    assert result["thread_id"].startswith("thesis:suite:")
    # El run_id viaja en el resultado y apunta al run grabado.
    assert result["run_id"] is not None
    # Durable run recorded with the full comparison payload.
    run = db.scalar(select(WorkflowRun).where(WorkflowRun.workflow_name == WORKFLOW_NAME))
    assert run is not None and run.status == "succeeded"
    assert run.result_payload["graph_execution"]["idempotent_retry"] is True


def test_shadow_without_classic_thesis_reports_divergence(db):
    _company(db)
    result = ThesisShadowService().run(db, ticker="AAPL", tenant_external_id="suite")
    assert any("no persisted thesis version" in d for d in result["divergences"])
    # The expected 6d skeleton divergence is always stated, not hidden.
    assert any("expected at 6d" in d for d in result["divergences"])


def _seed_model_and_valuation(db: Session, company_id: int):
    from app.models.entities import FundamentalModelVersion, FundamentalValuationSnapshot

    model = FundamentalModelVersion(
        company_id=company_id, version=3, engine_version="e1", algorithm_version="a1",
        framework_key="quality_compounder", horizon_years=5, status="final",
        publishable=True, input_fingerprint="fp-input-0123456789",
        forecast_fingerprint="fp-forecast", market_snapshot_fingerprint="fp-market",
        valuation_snapshot_fingerprint="fp-valuation", scenario_probabilities={},
        model_snapshot={},
    )
    db.add(model)
    db.flush()
    db.add(FundamentalValuationSnapshot(
        model_version_id=model.id, company_id=company_id, current_price=200,
        market_snapshot_fingerprint="fp-market",
        valuation_snapshot_fingerprint="fp-valuation-0123", snapshot={},
    ))
    db.commit()
    return model


def test_probe_comparison_matches_classic_state(db):
    from app.models.entities import RedTeamRun

    company = _company(db)
    model = _seed_model_and_valuation(db, company.id)
    db.add(RedTeamRun(company_id=company.id, status="completed", score=72,
                      prompt_version="red-team-v1"))
    db.commit()
    db.add(ThesisVersion(company_id=company.id, version=1, status="published",
                         thesis_markdown="# t", executive_summary="s"))
    db.commit()
    result = ThesisShadowService().run(db, ticker="AAPL", tenant_external_id="suite")
    probes = {entry["node"]: entry for entry in result["probe_comparison"]}
    assert set(probes) == {
        "resolve_company",
        "ensure_ingestion_complete",
        "build_fundamental_model",
        "deterministic_valuation",
        "source_audit",
        "deterministic_red_team",
    }
    assert all(entry["status"] == "match" for entry in probes.values())
    assert probes["resolve_company"]["graph_artifact"] == f"company:{company.id}"
    assert probes["build_fundamental_model"]["graph_artifact"] == (
        f"model:v{model.version}:{model.input_fingerprint[:12]}"
    )
    assert probes["deterministic_valuation"]["graph_artifact"].startswith("valuation:")
    assert probes["deterministic_red_team"]["graph_artifact"] == "redteam:1:score=72"
    assert not any("diverged" in d for d in result["divergences"])


def test_probe_comparison_honest_when_classic_state_absent(db):
    _company(db)
    result = ThesisShadowService().run(db, ticker="AAPL", tenant_external_id="suite")
    probes = {entry["node"]: entry for entry in result["probe_comparison"]}
    assert all(entry["status"] == "match" for entry in probes.values())
    assert probes["build_fundamental_model"]["graph_artifact"] == "model:none"
    assert probes["deterministic_valuation"]["graph_artifact"] == "valuation:none"
    assert probes["ensure_ingestion_complete"]["graph_artifact"] == (
        "evidence:facts=0,prices=0,docs=0"
    )
    assert probes["source_audit"]["graph_artifact"] == "audit:facts={}|docs={}|lowconf=0"
    assert probes["deterministic_red_team"]["graph_artifact"] == "redteam:none"


def test_every_classic_phase_is_mapped():
    assert set(THESIS_PHASES) <= set(PHASE_TO_NODE)
    for node in PHASE_TO_NODE.values():
        assert node in THESIS_GRAPH_NODES


def test_idempotency_key_replays_stored_run(db):
    _company(db)
    service = ThesisShadowService()
    first = service.run(db, ticker="AAPL", tenant_external_id="suite", idempotency_key="shadow-aapl-1")
    assert not first.get("idempotent_replay")
    second = service.run(db, ticker="AAPL", tenant_external_id="suite", idempotency_key="shadow-aapl-1")
    assert second["idempotent_replay"] is True
    assert second["run_id"] == first["run_id"]
    runs = db.scalars(
        select(WorkflowRun).where(WorkflowRun.workflow_name == WORKFLOW_NAME)
    ).all()
    assert len(runs) == 1
