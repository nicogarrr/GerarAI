"""Estados fallidos del job SOTP con modelos reales y sin LLM/broker."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, Tenant, WorkflowRun
from app.services import company_resolver
from app.services import sotp_agents_job as svc


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(Tenant(id=1, external_id="sotp-job-test"))
            session.flush()
            session.info["tenant_id"] = 1
            session.info["user_id"] = " actor "
            yield session
    finally:
        engine.dispose()


def _run(db):
    run = WorkflowRun(
        tenant_id=1,
        workflow_name=svc.WORKFLOW_NAME,
        status="queued",
        idempotency_key="sotp-test",
        input_payload={"ticker": "TEST"},
    )
    db.add(run)
    db.commit()
    return run


def test_enqueue_dispatch_roto_guarda_fallo_y_usuario(db):
    def broken(run):
        raise RuntimeError("no broker")

    run, made = svc.enqueue(db, "test", dispatch=broken)
    assert made is True and run.status == "failed"
    assert run.error_class == "RuntimeError" and run.error_message == "No se pudo encolar el trabajo"
    assert run.input_payload == {"ticker": "TEST", "tenant_id": 1, "user_id": "actor"}
    assert run.finished_at is not None
    assert svc.job_payload(None) is None


def test_utc_preserva_aware_y_ancla_naive():
    aware = datetime(2026, 1, 1, tzinfo=UTC)
    assert svc._utc(aware) is aware
    assert svc._utc(aware.replace(tzinfo=None)) == aware
    assert svc._utc(None) is None


def test_run_job_excepcion_persiste_clase_y_cierra(db, monkeypatch):
    run = _run(db)
    run_id = run.id

    def broken(db, ticker):
        raise ValueError("resolver")

    monkeypatch.setattr(company_resolver, "resolve_company", broken)
    engine = db.get_bind()
    svc.run_job(run_id, session_factory=lambda: Session(engine))
    db.expire_all()
    got = db.get(WorkflowRun, run_id)
    assert got.status == "failed" and got.error_class == "ValueError"
    assert got.finished_at is not None


def test_run_job_empresa_ausente_y_estado_terminal(db, monkeypatch):
    run = _run(db)
    monkeypatch.setattr(company_resolver, "resolve_company", lambda db, ticker: None)
    engine = db.get_bind()
    svc.run_job(run.id, session_factory=lambda: Session(engine))
    db.expire_all()
    assert run.status == "failed" and run.error_class == "sotp:no_company"
    assert run.result_payload == {"status": "no_company", "problems": ["empresa desconocida"]}
    before = run.finished_at
    svc.run_job(run.id, session_factory=lambda: Session(engine))
    db.expire_all()
    assert run.finished_at == before  # terminal: no se reejecuta
    svc.run_job(99999, session_factory=lambda: Session(engine))


def test_attach_disabled_no_tenant_empresa_ausente(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "thesis_sotp_agents_enabled", False)
    assert svc.attach_to_thesis_run(db, 1, "TEST", None) == {"status": "disabled"}
    monkeypatch.setattr(settings, "thesis_sotp_agents_enabled", True)
    db.info["tenant_id"] = None
    assert svc.attach_to_thesis_run(db, 1, "TEST", None) == {"status": "no_tenant"}
    db.info["tenant_id"] = 1
    monkeypatch.setattr(company_resolver, "resolve_company", lambda db, ticker: None)
    assert svc.attach_to_thesis_run(db, 99999, "TEST", None) == {"status": "no_company"}
