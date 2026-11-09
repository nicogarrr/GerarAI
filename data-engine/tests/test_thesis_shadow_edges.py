"""Honest shadow comparison reporting under simulated graph failures/divergence."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, WorkflowRun
from app.services import thesis_shadow_service as shadow


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(
                Company(
                    ticker="FIXTURE",
                    name="Fixture",
                    exchange="NASDAQ",
                    company_type="holding",
                    valuation_model="unassigned",
                )
            )
            session.commit()
            yield session
    finally:
        engine.dispose()


def graph_result(nodes=None, artifacts=None):
    return {
        "completed_nodes": list(shadow.THESIS_GRAPH_NODES) if nodes is None else nodes,
        "status": "fixture",
        "artifacts": artifacts or {},
    }


def install_graph(monkeypatch, first, second):
    graph = Mock()
    graph.invoke.side_effect = [first, second]
    graph.get_state.return_value = SimpleNamespace(next=())
    monkeypatch.setattr(shadow, "sqlite_checkpointer", lambda: nullcontext(object()))
    build = Mock(return_value=graph)
    monkeypatch.setattr(shadow, "build_thesis_graph", build)
    return graph, build


@pytest.mark.parametrize("artifact,status", [(None, "unobserved"), ("other", "divergent"), ("same", "match")])
def test_absent_probe_is_not_agreement(artifact, status):
    assert shadow._probe_entry("node", artifact, "same") == {
        "node": "node",
        "graph_artifact": artifact,
        "classic_observed": "same",
        "status": status,
    }


def test_incomplete_graph_retry_and_phase_gaps_are_all_reported(db, monkeypatch):
    graph, _ = install_graph(
        monkeypatch,
        graph_result(nodes=["resolve_company"], artifacts={"resolve_company": "company:wrong"}),
        graph_result(nodes=["resolve_company", "unexpected_retry_node"]),
    )
    monkeypatch.setattr(shadow, "THESIS_PHASES", ["unmapped_phase", "mapped_phase"])
    monkeypatch.setattr(shadow, "PHASE_TO_NODE", {"mapped_phase": "missing_graph_node"})
    result = shadow.ThesisShadowService().run(db, ticker="FIXTURE", tenant_external_id="fixture-tenant")
    assert result["graph_execution"]["nodes_in_order"] is False
    assert result["graph_execution"]["idempotent_retry"] is False
    assert result["graph_execution"]["retry_added_nodes"] == ["unexpected_retry_node"]
    assert result["graph_execution"]["approval_interrupt"]["interrupted_at_gate"] is False
    assert result["phase_mapping"]["complete"] is False
    assert result["phase_mapping"]["unmapped_phases"] == ["unmapped_phase"]
    assert result["phase_mapping"]["missing_graph_nodes"] == ["missing_graph_node"]
    divergences = result["divergences"]
    for expected in [
        "did not commit all nodes",
        "retry re-executed",
        "without graph node",
        "missing from graph",
        "probe resolve_company diverged",
        "reported no observation",
    ]:
        assert any(expected in message for message in divergences)
    assert graph.invoke.call_count == 2
    run = db.get(WorkflowRun, result["run_id"])
    assert run.result_payload["divergences"] == divergences


def test_graph_failure_records_failed_workflow_and_reraises_same_exception(db, monkeypatch):
    error = RuntimeError("local graph failure")
    graph, _ = install_graph(monkeypatch, {}, {})
    graph.invoke.side_effect = error
    with pytest.raises(RuntimeError) as exc:
        shadow.ThesisShadowService().run(db, ticker="FIXTURE", tenant_external_id="fixture-tenant")
    assert exc.value is error
    run = db.scalar(select(WorkflowRun).where(WorkflowRun.workflow_name == shadow.WORKFLOW_NAME))
    assert run.status == "failed"
    graph.invoke.assert_called_once()


def test_idempotent_replay_preserves_original_run_and_never_rebuilds_graph(db, monkeypatch):
    graph, build = install_graph(monkeypatch, graph_result(), graph_result())
    service = shadow.ThesisShadowService()
    first = service.run(
        db, ticker="FIXTURE", tenant_external_id="fixture-tenant", idempotency_key="fixture-key"
    )
    second = service.run(
        db, ticker="FIXTURE", tenant_external_id="fixture-tenant", idempotency_key="fixture-key"
    )
    assert second == {**first, "idempotent_replay": True}
    assert second["run_id"] == first["run_id"]
    build.assert_called_once()
    assert graph.invoke.call_count == 2
