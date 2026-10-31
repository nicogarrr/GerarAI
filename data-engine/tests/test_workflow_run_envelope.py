"""Stage 2: uniform workflow run envelope (workflow_runs + workflow_step_runs)."""

from sqlalchemy import select

import main
from app.core.database import SessionLocal, init_db
from app.models.entities import Company, WorkflowRun, WorkflowStepRun
from app.services.workflow_run_service import begin_run
from tests.auth_helpers import csrf_client


def _db():
    init_db()
    return SessionLocal()


def _cleanup(db):
    db.query(WorkflowStepRun).delete()
    db.query(WorkflowRun).delete()
    db.commit()


def test_begin_run_replays_prior_success_for_same_idempotency_key():
    db = _db()
    try:
        _cleanup(db)
        envelope = begin_run(
            db, "GenerateThesisWorkflow",
            execution_mode="deterministic",
            input_payload={"ticker": "AAPL"},
            idempotency_key="key-1",
        )
        assert envelope.replayed is False
        envelope.record_step(1, "generate_thesis", lambda: {"thesis_id": 7})
        envelope.finish({"status": "completed", "result": {"thesis_id": 7}})

        replay = begin_run(
            db, "GenerateThesisWorkflow",
            execution_mode="deterministic",
            input_payload={"ticker": "AAPL"},
            idempotency_key="key-1",
        )
        assert replay.replayed is True
        assert replay.run.id == envelope.run.id
        assert replay.run.result_payload["result"] == {"thesis_id": 7}

        # Una clave distinta siempre ejecuta de nuevo.
        fresh = begin_run(db, "GenerateThesisWorkflow", idempotency_key="key-2")
        assert fresh.replayed is False
        assert fresh.run.id != envelope.run.id
    finally:
        _cleanup(db)
        db.close()


def test_failed_step_marks_run_failed_with_error_class():
    db = _db()
    try:
        _cleanup(db)
        envelope = begin_run(db, "RedTeamWorkflow", idempotency_key="fail-1")

        def boom():
            raise ValueError("evidence gap")

        try:
            envelope.record_step(2, "execute_adversarial_review", boom)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("record_step must re-raise")

        db.expire_all()
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.idempotency_key == "fail-1"))
        assert run.status == "failed"
        assert run.error_class == "ValueError"
        assert "evidence gap" in run.error_message
        steps = db.scalars(select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)).all()
        assert len(steps) == 1
        assert steps[0].status == "failed"
        assert steps[0].error_class == "ValueError"
        assert steps[0].position == 2
    finally:
        _cleanup(db)
        db.close()


def test_failed_run_does_not_replay_but_allows_new_attempt():
    db = _db()
    try:
        _cleanup(db)
        envelope = begin_run(db, "RedTeamWorkflow", idempotency_key="fail-2")
        envelope.run.status = "failed"
        db.add(envelope.run)
        db.commit()

        second = begin_run(db, "RedTeamWorkflow", idempotency_key="fail-2")
        assert second.replayed is False
        assert second.run.id != envelope.run.id
    finally:
        _cleanup(db)
        db.close()


def test_generate_thesis_run_is_idempotent_over_http(monkeypatch):
    """Mismo Idempotency-Key: la segunda peticion devuelve el resultado guardado."""
    db = _db()
    try:
        _cleanup(db)
        if not db.scalar(select(Company).where(Company.ticker == "AAPL")):
            db.add(Company(ticker="AAPL", name="Apple Inc.", exchange="NASDAQ", company_type="compounders", valuation_model="dcf"))
            db.commit()
    finally:
        db.close()

    calls = {"count": 0}

    class FakeThesis:
        id = 42
        version = 3
        status = "approved"
        rating = "buy"

    class FakeThesisService:
        def generate(self, db, ticker, force_new_version=False):
            calls["count"] += 1
            return FakeThesis()

    monkeypatch.setattr(
        "app.services.thesis_service.ThesisService", FakeThesisService
    )

    client = csrf_client(main.app)
    headers = {"Idempotency-Key": "http-key-1"}
    first = client.post(
        "/api/workflows/GenerateThesisWorkflow/run",
        json={"ticker": "AAPL", "params": {}},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "completed"
    assert body["result"]["thesis_id"] == 42
    assert body["run_id"]
    assert calls["count"] == 1

    second = client.post(
        "/api/workflows/GenerateThesisWorkflow/run",
        json={"ticker": "AAPL", "params": {}},
        headers=headers,
    )
    assert second.status_code == 200
    replay = second.json()
    assert replay["idempotent_replay"] is True
    assert replay["run_id"] == body["run_id"]
    assert replay["result"]["thesis_id"] == 42
    # El trabajo no se ejecuta dos veces.
    assert calls["count"] == 1

    db = _db()
    try:
        steps = db.scalars(
            select(WorkflowStepRun).where(WorkflowStepRun.run_id == body["run_id"])
        ).all()
        assert [s.step_name for s in steps] == ["generate_thesis"]
        assert steps[0].status == "succeeded"
    finally:
        _cleanup(db)
        db.close()
