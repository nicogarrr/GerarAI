"""Un job de extraccion de principios cortado por el time limit de dramatiq
no puede quedarse en "running" para siempre.

TimeLimitExceeded hereda de BaseException (dramatiq Interrupt), asi que el
`except Exception` del actor no lo veia: el job quedaba en "running" y la ruta
POST /documents/{id}/extract-principles devolvia ese job "activo" en cada
peticion, sin volver a encolar nunca la extraccion de ese documento.
"""

from uuid import uuid4

import pytest
from dramatiq.middleware.time_limit import TimeLimitExceeded
from sqlalchemy import delete

import app.workers.dramatiq_app as workers
from app.core.database import SessionLocal, init_db
from app.models import KnowledgeChunk, KnowledgeDocument, ProcessingJob, Tenant
from app.seed import seed
from app.services.knowledge_library_service import KnowledgeLibraryService

ALL = {"include_all_tenants": True}


@pytest.fixture
def job_ids():
    init_db()
    seed()
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        tenant = Tenant(external_id=f"kn-tl-{suffix}", name="Knowledge time limit", status="active")
        db.add(tenant)
        db.commit()
        db.info["tenant_id"] = tenant.id
        ingested = KnowledgeLibraryService().ingest_bytes(
            db,
            title=f"Libro largo {suffix}",
            content=f"Compounding capital at high returns {suffix}.".encode(),
            filename="libro.txt",
            document_type="personal_note",
            author="audit",
            language="en",
            content_type="text/plain",
        )
        job = ProcessingJob(
            job_type="knowledge_principle_extraction",
            entity_type="knowledge_document",
            entity_id=ingested["knowledge_document_id"],
            status="queued",
            result={},
        )
        db.add(job)
        db.commit()
        ids = (tenant.id, job.id, ingested["knowledge_document_id"])
    yield ids
    tenant_id, job_id, document_id = ids
    with SessionLocal() as db:
        db.execute(delete(ProcessingJob).where(ProcessingJob.id == job_id).execution_options(**ALL))
        db.execute(
            delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_document_id == document_id).execution_options(**ALL)
        )
        db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id).execution_options(**ALL))
        db.commit()


def _job(job_id: int) -> ProcessingJob:
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id, execution_options=ALL)
        assert job is not None
        db.expunge(job)
        return job


def test_time_limit_marks_job_failed_and_still_reaches_dramatiq(monkeypatch, job_ids):
    tenant_id, job_id, _ = job_ids

    def interrupted(coroutine):
        # El TimeLimit de dramatiq interrumpe el hilo del actor mientras
        # espera a la corrutina de extraccion.
        coroutine.close()
        raise TimeLimitExceeded()

    monkeypatch.setattr(workers, "_run", interrupted)

    # Se re-lanza: el middleware Retries de dramatiq sigue decidiendo el reintento.
    with pytest.raises(TimeLimitExceeded):
        workers.extract_knowledge_principles.fn(job_id, tenant_id=tenant_id, user_id="kn-user")

    job = _job(job_id)
    assert job.status == "failed"
    assert job.completed_at is not None
    assert job.error


def test_retry_after_time_limit_runs_again(monkeypatch, job_ids):
    """El fallo marcado no impide el reintento de dramatiq: la siguiente
    entrega vuelve a "running" y termina."""
    tenant_id, job_id, _ = job_ids
    calls = {"n": 0}

    def flaky(coroutine):
        calls["n"] += 1
        if calls["n"] == 1:
            coroutine.close()
            raise TimeLimitExceeded()
        coroutine.close()
        return {"principles": [], "budget_stopped": False}

    monkeypatch.setattr(workers, "_run", flaky)
    with pytest.raises(TimeLimitExceeded):
        workers.extract_knowledge_principles.fn(job_id, tenant_id=tenant_id, user_id="kn-user")
    result = workers.extract_knowledge_principles.fn(job_id, tenant_id=tenant_id, user_id="kn-user")

    assert result["status"] == "ok"
    assert _job(job_id).status == "completed"
