"""Regresión: identidad e idempotencia de workflow runs (auditoría BE-02/BE-04).

BE-02: en la carrera entre dos primeras entregas con la misma clave, la que
pierde el INSERT no debe ejecutar el workflow una segunda vez si la rival
sigue "running", y debe normalizar una rival "failed" (attempt+1, estado
running) para que los steps no colisionen con
uq_workflow_step_runs_position_attempt.

BE-04: ThesisApprovalWorkflow debe referenciar SU run (el del envelope), no
"el último del tenant": con dos aprobaciones en marcha devolvía el run_id
equivocado.
"""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Tenant, WorkflowRun
from app.models.entities import Company
from app.services import workflow_run_service as wrs
from app.services.thesis_graph_approval_service import ThesisGraphApprovalService
from app.services.workflow_run_service import begin_run


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _tenant(db):
    tenant = Tenant(external_id="race", name="race")
    db.add(tenant)
    db.commit()
    db.info["tenant_id"] = tenant.id
    return tenant


def _rival(tenant_id, status):
    return WorkflowRun(
        tenant_id=tenant_id,
        workflow_name="WF",
        status=status,
        idempotency_key="race-key",
        input_payload={},
        attempt=1,
        started_at=wrs._utcnow(),
        error_class="Boom" if status == "failed" else None,
        error_message="boom" if status == "failed" else None,
        result_payload={"old": True} if status == "failed" else None,
    )


def _patch_race(monkeypatch, tenant_id, rival_status):
    """Simula que la otra petición gana el INSERT durante 'run start'."""
    real = wrs._safe_commit

    def fake_commit(session, label):
        if label == "run start":
            session.rollback()  # descarta nuestro run pendiente
            session.add(_rival(tenant_id, rival_status))
            session.commit()
            return False
        return real(session, label)

    monkeypatch.setattr(wrs, "_safe_commit", fake_commit)


def test_raced_running_rival_is_replayed_not_reexecuted(monkeypatch):
    db = _session()
    try:
        tenant = _tenant(db)
        _patch_race(monkeypatch, tenant.id, "running")
        envelope = begin_run(db, "WF", idempotency_key="race-key", tenant_id=tenant.id)
        assert envelope.replayed is True
        assert envelope.run.status == "running"
        assert db.query(WorkflowRun).count() == 1
    finally:
        db.close()


def test_raced_failed_rival_is_normalized_for_retry(monkeypatch):
    db = _session()
    try:
        tenant = _tenant(db)
        _patch_race(monkeypatch, tenant.id, "failed")
        envelope = begin_run(db, "WF", idempotency_key="race-key", tenant_id=tenant.id)
        assert envelope.replayed is False
        assert envelope.run.status == "running"
        assert envelope.run.attempt == 2
        assert envelope.run.error_class is None
        assert envelope.run.error_message is None
        assert envelope.run.result_payload is None
        assert db.query(WorkflowRun).count() == 1
    finally:
        db.close()


def _company(db, ticker):
    db.add(Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    ))
    db.commit()


def test_approval_start_returns_own_run_id(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _company(db, "AAPL")
        _company(db, "MSFT")
        svc = ThesisGraphApprovalService(
            checkpoint_path=str(tmp_path / "checkpoints.db"),
            database_url="sqlite:///./cavaai_test.db",
        )
        r1 = svc.start(db, ticker="AAPL", idempotency_key="ap-1")
        r2 = svc.start(db, ticker="MSFT", idempotency_key="ap-2")
        assert r1["run_id"] != r2["run_id"]
        for res, key in ((r1, "ap-1"), (r2, "ap-2")):
            run = db.scalar(select(WorkflowRun).where(WorkflowRun.idempotency_key == key))
            assert run is not None
            assert res["run_id"] == run.id
        # El replay devuelve el MISMO run_id (no el último del tenant).
        r1b = svc.start(db, ticker="AAPL", idempotency_key="ap-1")
        assert r1b["idempotent_replay"] is True
        assert r1b["run_id"] == r1["run_id"]