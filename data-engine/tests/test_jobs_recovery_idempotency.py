"""Regresiones de recuperacion/idempotencia de jobs (auditoria J1-J4)."""

import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from dramatiq.middleware.time_limit import TimeLimitExceeded
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.llm.errors import ProviderHTTPError, ProviderTransportError
from app.models.entities import WorkflowRun, WorkflowStepRun
from app.services import thesis_job_service as j


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    WorkflowRun.__table__.create(engine)
    WorkflowStepRun.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(j, "_dispatch_run", lambda run: None)
    monkeypatch.setattr(j, "build_run_guard", lambda *a, **k: None)
    monkeypatch.setattr(
        j, "get_settings", lambda: types.SimpleNamespace(research_auth_required=False, is_production=False)
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "app.services.company_enrichment_service",
        types.SimpleNamespace(ensure_company_stub=lambda *a: None),
    )
    return factory, engine


def _fake_thesis(monkeypatch, calls, exc=None):
    class Fake:
        def generate(self, db, ticker, **kwargs):
            calls.append(ticker)
            if exc is not None:
                raise exc
            return types.SimpleNamespace(id=len(calls), version=len(calls), status="final")

    monkeypatch.setitem(
        __import__("sys").modules, "app.services.thesis_service", types.SimpleNamespace(ThesisService=Fake)
    )


def test_j2_failed_old_request_id_does_not_bypass_active_run(env):
    factory, _ = env
    with factory() as db:
        db.info["tenant_id"] = 1
        old = WorkflowRun(
            tenant_id=1, workflow_name=j.WORKFLOW_NAME, status="failed",
            idempotency_key=j.idempotency_key_for("AAPL", True, "old"),
            input_payload={"ticker": "AAPL", "force": True}, attempt=1,
        )
        new = WorkflowRun(
            tenant_id=1, workflow_name=j.WORKFLOW_NAME, status="running",
            idempotency_key=j.idempotency_key_for("AAPL", True, "new"),
            input_payload={"ticker": "AAPL", "force": True}, attempt=1, started_at=datetime.now(UTC),
        )
        db.add_all([old, new])
        db.commit()
        run, created = j.enqueue_generation(db, "AAPL", True, "old")
        assert (run.id, created) == (new.id, False)
        assert old.status == "failed" and new.status == "running"


def test_j2_failed_replay_still_requeues_when_nothing_active(env):
    factory, _ = env
    with factory() as db:
        db.info["tenant_id"] = 1
        old = WorkflowRun(
            tenant_id=1, workflow_name=j.WORKFLOW_NAME, status="failed",
            idempotency_key=j.idempotency_key_for("AAPL", True, "old"),
            input_payload={"ticker": "AAPL", "force": True}, attempt=1,
        )
        db.add(old)
        db.commit()
        run, _created = j.enqueue_generation(db, "AAPL", True, "old")
        assert run.id == old.id and old.attempt == 2


def test_j1_expired_lease_recovery_claims_without_releasing_lock(env, monkeypatch):
    factory, engine = env
    calls: list = []
    _fake_thesis(monkeypatch, calls)
    with factory() as db:
        stale = WorkflowRun(
            workflow_name=j.WORKFLOW_NAME, status="running",
            input_payload={"ticker": "RACE", "force": True}, attempt=1,
            started_at=datetime.now(UTC) - timedelta(hours=7),
        )
        db.add(stale)
        db.commit()
        rid = stale.id
    seen: list[str] = []
    handoff: list[bool] = []

    class Interleaved(Session):
        def commit(self):
            super().commit()
            if handoff:
                return
            handoff.append(True)
            with factory() as obs:
                seen.append(obs.get(WorkflowRun, rid).status)
            # Otra entrega llega justo tras el primer commit de la recuperacion.
            j.SessionLocal = factory
            j.run_thesis_job(rid)

    monkeypatch.setattr(
        j, "SessionLocal", sessionmaker(engine, class_=Interleaved, expire_on_commit=False, autoflush=False)
    )
    j.run_thesis_job(rid)
    with factory() as db:
        done = db.get(WorkflowRun, rid)
        assert seen == ["running"]  # nunca un "retrying" intermedio reclamable
        assert len(calls) == 1
        assert done.status == "succeeded" and done.attempt == 2


@pytest.mark.parametrize(
    "exc",
    [ProviderHTTPError("p", 503), ProviderHTTPError("p", 429), ProviderTransportError("p", "read_timeout", 2)],
)
def test_j3_provider_errors_are_retried_not_terminal(env, monkeypatch, exc):
    factory, engine = env
    calls: list = []
    _fake_thesis(monkeypatch, calls, exc)
    monkeypatch.setattr(j, "SessionLocal", factory)
    with factory() as db:
        run = WorkflowRun(workflow_name=j.WORKFLOW_NAME, status="queued",
                          input_payload={"ticker": "T", "force": True}, attempt=1)
        db.add(run)
        db.commit()
        rid = run.id
    with pytest.raises(type(exc)):
        j.run_thesis_job(rid)
    with factory() as db:
        assert db.get(WorkflowRun, rid).status == "retrying"
    with pytest.raises(type(exc)):  # la re-entrega ya no se descarta
        j.run_thesis_job(rid)
    assert len(calls) == 2


def test_j3_permanent_provider_http_error_stays_terminal():
    assert not j._is_retryable_error(ProviderHTTPError("p", 401))


def test_j4_timelimit_marks_failed_and_stale_processing_is_requeueable():
    from app.api.routes.knowledge_rag import _processing_abandoned
    from app.models.knowledge_rag import KnowledgeRagParent, KnowledgeRagSource
    from app.services.knowledge_rag.chunking import ChunkConfig
    from app.services.knowledge_rag.domain import DocType, SourceMetadata
    from app.services.knowledge_rag.ingest import index_source, register_source

    engine = create_engine("sqlite:///:memory:")
    KnowledgeRagSource.__table__.create(engine)
    KnowledgeRagParent.__table__.create(engine)
    with Session(engine, expire_on_commit=False) as db, TemporaryDirectory() as td:
        p = Path(td) / "s.txt"
        p.write_text("synthetic document")
        meta = SourceMetadata(title="s", source_uri="local:s", language="es", doc_type=DocType.MEMO)
        r = register_source(db, path=p, relative_path=p.name, meta=meta, tenant_id=1)

        def interrupted(_p):
            raise TimeLimitExceeded()

        with pytest.raises(TimeLimitExceeded):
            index_source(db, r.source.id, path=p, store=object(), embedder=object(),
                         extractor=interrupted, counter=len, config=ChunkConfig())
        db.expire_all()
        src = db.get(KnowledgeRagSource, r.source.id)
        assert src.status == "failed" and "TimeLimitExceeded" in (src.error or "")
        # SIGKILL: processing sin actividad > 2 h se considera abandonado.
        src.status = "processing"
        src.updated_at = datetime.now(UTC) - timedelta(hours=3)
        assert _processing_abandoned(src)
        src.updated_at = datetime.now(UTC) - timedelta(minutes=5)
        assert not _processing_abandoned(src)


def test_j4_abandoned_threshold_is_tied_to_actor_time_limit():
    from app.api.routes.knowledge_rag import PROCESSING_ABANDONED_AFTER
    from app.services.knowledge_rag.runtime import INGEST_TIME_LIMIT_MS
    from app.workers.knowledge_rag_actors import ingest_knowledge_source

    assert ingest_knowledge_source.options["time_limit"] == INGEST_TIME_LIMIT_MS
    assert timedelta(milliseconds=2 * INGEST_TIME_LIMIT_MS) == PROCESSING_ABANDONED_AFTER
