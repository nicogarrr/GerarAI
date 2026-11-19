"""extract_knowledge_principles: progreso persistido, corte por presupuesto
marca partial (nunca exito completo), TimeLimitExceeded marca failed y se
relanza (el job nunca se queda en running), errores con mensaje legible."""

from types import SimpleNamespace

import pytest
from dramatiq.middleware.time_limit import TimeLimitExceeded
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.knowledge_library_service as kls
from app.models import KnowledgeDocument, ProcessingJob
from app.models.entities import Base
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)
    outcome = {"value": {"principles": [SimpleNamespace(id=5)], "batches": 1}}
    progress_calls = []

    class FakeService:
        async def extract_principle_batches(self, db_, document, progress):
            value = outcome["value"]
            if isinstance(value, BaseException):
                raise value
            progress(1, 1)
            return dict(value)

    monkeypatch.setattr(kls, "KnowledgeLibraryService", FakeService)
    return SimpleNamespace(db=db, outcome=outcome, progress_calls=progress_calls)


def _job(db):
    doc = KnowledgeDocument(tenant_id=1, title="carta", document_type="letter")
    db.add(doc)
    db.flush()
    job = ProcessingJob(tenant_id=1, job_type="knowledge_extraction",
                        entity_type="knowledge_document", entity_id=doc.id)
    db.add(job)
    db.commit()
    return job


def test_ok_completa_con_ids_y_progreso(env):
    job = _job(env.db)
    out = worker.extract_knowledge_principles.fn(job.id, tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["principle_ids"] == [5]
    env.db.expire_all()
    job = env.db.get(ProcessingJob, job.id)
    assert job.status == "completed"
    assert job.progress_current == 1 and job.progress_total == 1
    assert job.completed_at is not None


def test_corte_por_presupuesto_es_partial_no_exito(env):
    job = _job(env.db)
    env.outcome["value"] = {"principles": [], "budget_stopped": True}
    out = worker.extract_knowledge_principles.fn(job.id, tenant_id=1, user_id="u")
    assert out["status"] == "ok"  # el actor completo; el JOB queda partial
    env.db.expire_all()
    assert env.db.get(ProcessingJob, job.id).status == "partial"


def test_job_inexistente_es_error(env):
    out = worker.extract_knowledge_principles.fn(999, tenant_id=1, user_id="u")
    assert out["status"] == "error"
    assert "not found" in out["error"]["message"]


def test_error_marca_failed_con_mensaje_legible(env):
    job = _job(env.db)
    env.outcome["value"] = RuntimeError("modelo caido")
    out = worker.extract_knowledge_principles.fn(job.id, tenant_id=1, user_id="u")
    assert out["status"] == "error"
    env.db.expire_all()
    job = env.db.get(ProcessingJob, job.id)
    assert job.status == "failed" and job.error
    assert job.completed_at is not None


def test_error_con_diagnostico_se_persiste(env):
    job = _job(env.db)
    exc = RuntimeError("cuota")
    exc.diagnostic = {"provider": "go", "status": 429}
    env.outcome["value"] = exc
    worker.extract_knowledge_principles.fn(job.id, tenant_id=1, user_id="u")
    env.db.expire_all()
    job = env.db.get(ProcessingJob, job.id)
    assert job.result["error_diagnostic"] == {"provider": "go", "status": 429}


def test_time_limit_marca_failed_y_relanza(env):
    job = _job(env.db)
    env.outcome["value"] = TimeLimitExceeded("limite")
    with pytest.raises(TimeLimitExceeded):
        worker.extract_knowledge_principles.fn(job.id, tenant_id=1, user_id="u")
    env.db.expire_all()
    job = env.db.get(ProcessingJob, job.id)
    assert job.status == "failed"  # nunca se queda en running
    assert "tiempo" in job.error
