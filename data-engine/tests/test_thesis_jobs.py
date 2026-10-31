"""W7a: async thesis generation jobs — enqueue idempotency, honest phases,
failure classification, duplicate-delivery safety, status endpoint."""

from datetime import timedelta

import pytest
from sqlalchemy import select

import main
from app.core.database import SessionLocal, init_db
from app.models.entities import WorkflowRun, WorkflowStepRun
from app.seed import seed
from app.services import thesis_job_service as jobs
from app.services.thesis_service import ThesisService
from tests.auth_helpers import csrf_client


@pytest.fixture(autouse=True)
def _db():
    init_db()
    seed()
    yield
    db = SessionLocal()
    for model in (WorkflowStepRun, WorkflowRun):
        db.query(model).delete()
    db.commit()
    db.close()


def _fake_generate(thesis_id=7):
    def generate(self, db, ticker, force_new_version=False, phase_callback=None):
        for phase in jobs.THESIS_PHASES:
            if phase_callback:
                phase_callback(phase)

        class _T:
            id = thesis_id
            version = 3
            status = "final"

        return _T()

    return generate


def _enqueue_without_dispatch(
    monkeypatch,
    ticker="AAPL",
    force=False,
    *,
    tenant_id=None,
    user_id=None,
    send=None,
    request_id=None,
):
    import app.workers.dramatiq_app as workers

    monkeypatch.setattr(workers.generate_thesis_job, "send", send or (lambda run_id: None))
    db = SessionLocal()
    if tenant_id is not None:
        db.info["tenant_id"] = tenant_id
    if user_id is not None:
        db.info["user_id"] = user_id
    try:
        return jobs.enqueue_generation(db, ticker, force, request_id)
    finally:
        db.close()


def test_enqueue_persists_tenant_and_user_context(monkeypatch):
    from uuid import uuid4

    from app.models import Tenant

    external_id = f"thesis-enqueue-tenant-{uuid4().hex[:8]}"
    db = SessionLocal()
    tenant = Tenant(
        external_id=external_id,
        name="Thesis enqueue tenant",
        metadata_={"created_by": "thesis-enqueue-user"},
    )
    db.add(tenant)
    db.commit()
    tenant_id = tenant.id
    db.close()

    try:
        run, created = _enqueue_without_dispatch(
            monkeypatch,
            ticker="AAPL",
            tenant_id=tenant_id,
            user_id="thesis-enqueue-user",
        )

        assert created is True
        assert run.tenant_id == tenant_id
        assert run.input_payload["user_id"] == "thesis-enqueue-user"
    finally:
        db = SessionLocal()
        tenant = db.query(Tenant).filter_by(id=tenant_id).one_or_none()
        if tenant is not None:
            db.delete(tenant)
            db.commit()
        db.close()


def test_enqueue_is_idempotent_while_active(monkeypatch):
    run1, created1 = _enqueue_without_dispatch(monkeypatch)
    run2, created2 = _enqueue_without_dispatch(monkeypatch)
    assert created1 is True and created2 is False
    assert run1.id == run2.id
    assert run1.status == "queued"
    assert run1.input_payload["ticker"] == "AAPL"
    assert run1.input_payload["force"] is False
    assert run1.input_payload["dispatch_sent_at"]
    # force=True is a different key -> a second job may coexist
    run3, created3 = _enqueue_without_dispatch(monkeypatch, force=True)
    assert created3 is True and run3.id != run1.id


def test_run_job_records_real_phases_and_result(monkeypatch):
    monkeypatch.setattr(ThesisService, "generate", _fake_generate())
    run, _ = _enqueue_without_dispatch(monkeypatch)
    jobs.run_thesis_job(run.id)

    db = SessionLocal()
    stored = db.get(WorkflowRun, run.id)
    assert stored.status == "succeeded"
    assert stored.result_payload == {"thesis_version_id": 7, "version": 3, "status": "final"}
    assert stored.started_at and stored.finished_at
    steps = db.scalars(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id).order_by(WorkflowStepRun.position)
    ).all()
    assert [s.step_name for s in steps] == list(jobs.THESIS_PHASES)
    assert all(s.status == "succeeded" for s in steps)
    db.close()


def test_run_job_failure_marks_failed_and_reraises(monkeypatch):
    def boom(self, db, ticker, force_new_version=False, phase_callback=None):
        if phase_callback:
            phase_callback("collect_evidence")
        raise RuntimeError("SEC timeout")

    monkeypatch.setattr(ThesisService, "generate", boom)
    run, _ = _enqueue_without_dispatch(monkeypatch)
    with pytest.raises(RuntimeError):
        jobs.run_thesis_job(run.id)

    db = SessionLocal()
    stored = db.get(WorkflowRun, run.id)
    assert stored.status == "failed"
    assert stored.error_class == "RuntimeError"
    assert stored.error_message == "Thesis generation failed"
    failed_step = db.scalars(select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)).first()
    assert failed_step.status == "failed"
    assert failed_step.error_class == "RuntimeError"
    db.close()


def test_duplicate_delivery_after_terminal_is_noop(monkeypatch):
    monkeypatch.setattr(ThesisService, "generate", _fake_generate())
    run, _ = _enqueue_without_dispatch(monkeypatch)
    jobs.run_thesis_job(run.id)
    jobs.run_thesis_job(run.id)  # duplicate delivery: no re-execution, no error

    db = SessionLocal()
    stored = db.get(WorkflowRun, run.id)
    assert stored.status == "succeeded"
    assert db.query(WorkflowStepRun).filter_by(run_id=run.id).count() == len(jobs.THESIS_PHASES)
    db.close()


def test_enqueue_retry_state_is_reused(monkeypatch):
    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="RETRYING")
    db = SessionLocal()
    stored = db.get(WorkflowRun, run.id)
    stored.status = "retrying"
    stored.attempt = 1
    db.commit()
    db.close()

    replay, created = _enqueue_without_dispatch(monkeypatch, ticker="RETRYING")
    assert created is False
    assert replay.id == run.id


def test_status_endpoint_payload(monkeypatch):
    monkeypatch.setattr(ThesisService, "generate", _fake_generate())
    run, _ = _enqueue_without_dispatch(monkeypatch)
    jobs.run_thesis_job(run.id)

    client = csrf_client(main.app)
    response = client.get(f"/api/thesis/jobs/{run.id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["ticker"] == "AAPL"
    assert len(payload["phases"]) == len(jobs.THESIS_PHASES)
    assert payload["current_phase"] is None
    assert payload["result"]["thesis_version_id"] == 7
    assert "estimated" not in str(payload).lower()  # no invented ETAs
    assert client.get("/api/thesis/jobs/999999").status_code == 404


def test_enqueue_returns_succeeded_run_without_unique_key_error(monkeypatch):
    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="TERMINAL")
    db = SessionLocal()
    stored = db.get(WorkflowRun, run.id)
    stored.status = "succeeded"
    db.commit()
    db.close()

    replay, created = _enqueue_without_dispatch(monkeypatch, ticker="TERMINAL")

    assert created is False
    assert replay.id == run.id
    assert replay.status == "succeeded"


def test_failed_run_is_redispatched_on_retry(monkeypatch):
    """El front dice "puedes reintentar": un run fallido no es un resultado
    reutilizable - re-postear el mismo ticker debe re-despachar el run."""
    sent: list[int] = []
    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="RETRY")
    db = SessionLocal()
    stored = db.get(WorkflowRun, run.id)
    stored.status = "failed"
    stored.error_class = "ValueError"
    stored.error_message = "Thesis generation failed"
    db.commit()
    db.close()

    replay, created = _enqueue_without_dispatch(
        monkeypatch, ticker="RETRY", send=lambda run_id: sent.append(run_id)
    )

    assert created is False
    assert replay.id == run.id
    assert replay.status == "queued"
    assert replay.error_class is None
    assert replay.error_message is None
    assert sent == [run.id]
    assert (replay.input_payload or {}).get("attempt") == 2


def test_generate_async_defers_company_enrichment_to_worker(monkeypatch):
    """Enqueue must persist before any slow provider request."""
    import app.workers.dramatiq_app as workers

    monkeypatch.setattr(workers.generate_thesis_job, "send", lambda run_id: None)

    def no_enrichment_on_request(*args, **kwargs):
        raise AssertionError("Network enrichment must not run in the request")

    monkeypatch.setattr(
        "app.services.company_enrichment_service.ensure_company_stub",
        no_enrichment_on_request,
    )
    response = csrf_client(main.app).post(
        "/api/thesis/generate-async",
        json={"ticker": "ZZTEST", "force_new_version": False},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"


def test_failed_dispatch_is_recoverable(monkeypatch):
    import app.workers.dramatiq_app as workers

    def fail_send(_run_id):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(workers.generate_thesis_job, "send", fail_send)
    run, created = _enqueue_without_dispatch(monkeypatch, ticker="DISPATCH", send=fail_send)
    assert created is True
    assert run.status == "dispatch_failed"

    sent: list[int] = []
    replay, replay_created = _enqueue_without_dispatch(
        monkeypatch, ticker="DISPATCH", send=lambda run_id: sent.append(run_id)
    )

    assert replay_created is False
    assert replay.id == run.id
    assert replay.status == "queued"
    assert sent == [run.id]


def test_expired_running_delivery_is_recovered(monkeypatch):
    monkeypatch.setattr(ThesisService, "generate", _fake_generate())
    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="STALE")
    db = SessionLocal()
    stored = db.get(WorkflowRun, run.id)
    stored.status = "running"
    stored.started_at = stored.created_at - jobs.RUNNING_LEASE - timedelta(minutes=1)
    db.commit()
    db.close()

    jobs.run_thesis_job(run.id)

    db = SessionLocal()
    recovered = db.get(WorkflowRun, run.id)
    assert recovered.status == "succeeded"
    assert recovered.attempt >= 2
    db.close()


def test_queued_run_without_dispatch_marker_is_recoverable(monkeypatch):
    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="QUEUED_RECOVER")
    db = SessionLocal()
    stored = db.get(WorkflowRun, run.id)
    payload = dict(stored.input_payload or {})
    payload.pop("dispatch_sent_at", None)
    stored.input_payload = payload
    db.commit()
    db.close()

    sent: list[int] = []
    replay, created = _enqueue_without_dispatch(
        monkeypatch, ticker="QUEUED_RECOVER", send=lambda run_id: sent.append(run_id)
    )
    assert created is False
    assert replay.id == run.id
    assert sent == [run.id]
    assert replay.input_payload["dispatch_sent_at"]


def test_same_ticker_key_is_scoped_by_tenant(monkeypatch):
    from uuid import uuid4

    from app.models import Tenant

    ids = []
    db = SessionLocal()
    for label in ("A", "B"):
        tenant = Tenant(
            external_id=f"thesis-scope-{label}-{uuid4().hex[:8]}",
            name=f"Tenant {label}",
            metadata_={"created_by": f"user-{label}"},
        )
        db.add(tenant)
        db.flush()
        ids.append(tenant.id)
    db.commit()
    db.close()
    try:
        run_a, created_a = _enqueue_without_dispatch(
            monkeypatch, ticker="SCOPED", tenant_id=ids[0], user_id="user-A"
        )
        run_b, created_b = _enqueue_without_dispatch(
            monkeypatch, ticker="SCOPED", tenant_id=ids[1], user_id="user-B"
        )
        assert created_a and created_b
        assert run_a.id != run_b.id
    finally:
        db = SessionLocal()
        db.query(WorkflowRun).filter(WorkflowRun.id.in_([run_a.id, run_b.id])).delete(
            synchronize_session=False
        )
        db.query(Tenant).filter(Tenant.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_request_id_permite_nueva_generacion_real_tras_exito(monkeypatch):
    """El boton de la UI manda un request_id nuevo por click: cada click debe
    crear un run real, no replayar el exitoso anterior. Sin request_id se
    conserva el replay (compat)."""
    run1, created1 = _enqueue_without_dispatch(monkeypatch, ticker="FRESH", request_id="click-0001")
    db = SessionLocal()
    stored = db.get(WorkflowRun, run1.id)
    stored.status = "succeeded"
    db.commit()
    db.close()

    run2, created2 = _enqueue_without_dispatch(monkeypatch, ticker="FRESH", request_id="click-0002")
    assert created2 is True
    assert run2.id != run1.id

    replay, created3 = _enqueue_without_dispatch(monkeypatch, ticker="FRESH", request_id="click-0001")
    assert created3 is False
    assert replay.id == run1.id


def test_different_click_ids_recover_same_active_generation(monkeypatch):
    first, _ = _enqueue_without_dispatch(monkeypatch, request_id="tab-1")
    second, created = _enqueue_without_dispatch(monkeypatch, request_id="tab-2")
    assert not created
    assert first.id == second.id


def test_latest_endpoint_recovers_after_request_session_is_closed(monkeypatch):
    run, _ = _enqueue_without_dispatch(monkeypatch, request_id="leaving-page")
    client = csrf_client(main.app)
    response = client.get("/api/thesis/jobs", params={"ticker": "aapl"})
    assert response.status_code == 200
    assert response.json()["job"]["id"] == run.id
    # No browser polls/start action between enqueue and worker execution.
    monkeypatch.setattr(ThesisService, "generate", _fake_generate())
    jobs.run_thesis_job(run.id)
    recovered = client.get("/api/thesis/jobs", params={"ticker": "AAPL"}).json()["job"]
    assert recovered["id"] == run.id
    assert recovered["status"] == "succeeded"
    assert client.get("/api/thesis/jobs", params={"ticker": "NOJOB"}).json() == {"job": None}


def test_dispatch_failed_recovery_needs_no_browser(monkeypatch):
    def unavailable(_run_id):
        raise ConnectionError("redis unavailable")

    run, _ = _enqueue_without_dispatch(monkeypatch, send=unavailable)
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        stored.updated_at = stored.created_at - jobs.DISPATCH_RECHECK - timedelta(minutes=1)
        db.commit()

    sent = []
    import app.workers.dramatiq_app as workers

    def deliver(run_id):
        # A fresh connection must see QUEUED before delivery can start.
        with SessionLocal() as db:
            assert db.get(WorkflowRun, run_id).status == "queued"
        sent.append(run_id)

    monkeypatch.setattr(workers.generate_thesis_job, "send", deliver)
    assert jobs.reconcile_thesis_dispatches() == {"redispatched": 1, "dispatch_failed": 0}
    assert sent == [run.id]
    assert jobs.reconcile_thesis_dispatches() == {"redispatched": 0, "dispatch_failed": 0}


def test_reconciler_does_not_restart_healthy_active_or_terminal_runs(monkeypatch):
    """Un run SANO nunca se re-despacha: lease de ejecucion fresco (running),
    reintento de dramatiq aun pendiente (retrying reciente) o estado terminal.
    Los runs interrumpidos de verdad los cubren los tests stale_*."""
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    sent = []
    for status in ("running", "succeeded", "failed", "retrying"):
        run, _ = _enqueue_without_dispatch(monkeypatch, ticker=status.upper())
        with SessionLocal() as db:
            stored = db.get(WorkflowRun, run.id)
            stored.status = status
            if status == "running":
                # Lease fresco: un worker sano esta generando ahora mismo.
                stored.started_at = _dt.now(_UTC)
            else:
                # retrying reciente: su reintento de dramatiq aun no vencio;
                # terminales: updated_at reciente, sin nada que recuperar.
                stored.updated_at = _dt.now(_UTC)
            db.commit()
    import app.workers.dramatiq_app as workers

    monkeypatch.setattr(workers.generate_thesis_job, "send", lambda run_id: sent.append(run_id))
    assert jobs.reconcile_thesis_dispatches() == {"redispatched": 0, "dispatch_failed": 0}
    assert sent == []


def test_reconciler_redelivers_stale_running_run_once(monkeypatch):
    """Worker muerto a mitad de la generacion: la entrega reencolada por el
    broker fue descartada por el lease fresco y nadie volveria a llamar al
    run. El reconciler re-entrega UNA vez y sella; el status lo mueve el
    worker, nunca el reconciler."""
    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="STUCKRUN")
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        stored.status = "running"
        stored.started_at = stored.created_at - jobs.RUNNING_LEASE - timedelta(minutes=1)
        stored.updated_at = stored.created_at - jobs.DISPATCH_RECHECK - timedelta(minutes=1)
        db.commit()
    sent = []
    import app.workers.dramatiq_app as workers

    monkeypatch.setattr(workers.generate_thesis_job, "send", lambda run_id: sent.append(run_id))
    assert jobs.reconcile_thesis_dispatches()["redispatched"] == 1
    assert sent == [run.id]
    # Sin multiplicar despachos: el sello de la re-entrega frena los ticks siguientes.
    assert jobs.reconcile_thesis_dispatches()["redispatched"] == 0
    assert sent == [run.id]
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        assert stored.status == "running"
        assert stored.input_payload["recovery_sent_at"]


def test_stale_running_redelivery_recovers_through_worker(monkeypatch):
    """Cadena completa proceso muerto -> reconciler -> worker: el intento
    recuperado termina y arranca con started_at FRESCO."""
    monkeypatch.setattr(ThesisService, "generate", _fake_generate())
    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="STALEOK")
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        stale_started = stored.created_at - jobs.RUNNING_LEASE - timedelta(minutes=1)
        stored.status = "running"
        stored.started_at = stale_started
        stored.updated_at = stored.created_at - jobs.DISPATCH_RECHECK - timedelta(minutes=1)
        db.commit()
    sent = []
    import app.workers.dramatiq_app as workers

    monkeypatch.setattr(workers.generate_thesis_job, "send", lambda run_id: sent.append(run_id))
    assert jobs.reconcile_thesis_dispatches()["redispatched"] == 1
    assert sent == [run.id]

    jobs.run_thesis_job(run.id)

    with SessionLocal() as db:
        recovered = db.get(WorkflowRun, run.id)
        assert recovered.status == "succeeded"
        assert recovered.attempt >= 2
        assert recovered.started_at is not None and recovered.started_at > stale_started


def test_recovered_attempt_drops_duplicate_delivery(monkeypatch):
    """Concurrencia: una entrega duplicada que llega MIENTRAS el intento
    recuperado genera debe caer por lease fresco, no re-disparar la
    recuperacion a mitad de la generacion (doble generacion concurrente)."""
    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="DUPDROP")
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        stored.status = "running"
        stored.started_at = stored.created_at - jobs.RUNNING_LEASE - timedelta(minutes=1)
        db.commit()

    deliveries = {"generate": 0}
    real_generate = _fake_generate()

    def generate_and_duplicate(self, db, ticker, force_new_version=False, phase_callback=None):
        deliveries["generate"] += 1
        # Entrega duplicada a mitad de la generacion (proceso aparte).
        jobs.run_thesis_job(run.id)
        return real_generate(self, db, ticker, force_new_version, phase_callback)

    monkeypatch.setattr(ThesisService, "generate", generate_and_duplicate)
    jobs.run_thesis_job(run.id)

    assert deliveries["generate"] == 1
    with SessionLocal() as db:
        recovered = db.get(WorkflowRun, run.id)
        assert recovered.status == "succeeded"
        assert recovered.attempt == 2


def test_reconciler_redelivers_lost_retrying_run(monkeypatch):
    """El reintento de dramatiq se perdio con la cola: un run "retrying" cuyo
    updated_at supera DISPATCH_RECHECK recibe una entrega nueva, una sola vez."""
    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="LOSTRETRY")
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        stored.status = "retrying"
        stored.updated_at = stored.created_at - jobs.DISPATCH_RECHECK - timedelta(minutes=1)
        db.commit()
    sent = []
    import app.workers.dramatiq_app as workers

    monkeypatch.setattr(workers.generate_thesis_job, "send", lambda run_id: sent.append(run_id))
    assert jobs.reconcile_thesis_dispatches()["redispatched"] == 1
    assert sent == [run.id]
    assert jobs.reconcile_thesis_dispatches()["redispatched"] == 0
    assert sent == [run.id]


def test_interrupted_redelivery_send_failure_retries_next_tick(monkeypatch):
    """Si el envio falla no se sella nada: el run sigue elegible de inmediato
    y el fallo cuenta como dispatch_failed."""
    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="SENDFAIL")
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        stored.status = "running"
        stored.started_at = stored.created_at - jobs.RUNNING_LEASE - timedelta(minutes=1)
        stored.updated_at = stored.created_at - jobs.DISPATCH_RECHECK - timedelta(minutes=1)
        db.commit()
    import app.workers.dramatiq_app as workers

    def fail_send(_run_id):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(workers.generate_thesis_job, "send", fail_send)
    assert jobs.reconcile_thesis_dispatches()["dispatch_failed"] == 1
    assert jobs.reconcile_thesis_dispatches()["dispatch_failed"] == 1


def test_time_limit_exceeded_marks_retrying_and_recovers(monkeypatch):
    """El limite efectivo por entrega (TimeLimit del broker, 10 min por
    defecto en dramatiq 2.2.1; el actor no lo sobrescribe) corta la
    generacion con un BaseException: debe quedar retrying acotado y
    recuperarse, no un run 'running' hasta el lease de 6 h."""
    from dramatiq.middleware.time_limit import TimeLimitExceeded

    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="TLIMIT")
    calls = {"n": 0}

    def flaky(self, db, ticker, force_new_version=False, phase_callback=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeLimitExceeded("deadline")
        return _fake_generate()(self, db, ticker, force_new_version, phase_callback)

    monkeypatch.setattr(ThesisService, "generate", flaky)
    with pytest.raises(TimeLimitExceeded):
        jobs.run_thesis_job(run.id)
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        assert stored.status == "retrying"
        assert stored.error_class == "TimeLimitExceeded"

    jobs.run_thesis_job(run.id)
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        assert stored.status == "succeeded" and stored.attempt == 2


def _steal_run(run_id: int) -> None:
    """Otra entrega (recuperacion por lease expirado) toma el run: attempt+1."""
    with SessionLocal() as other:
        stolen = other.get(WorkflowRun, run_id)
        stolen.attempt = int(stolen.attempt or 1) + 1
        stolen.status = "running"
        other.commit()


def test_fenced_success_cannot_overwrite_recovered_run(monkeypatch):
    """El commit de exito de un intento cercado se descarta: el run pertenece
    al intento que lo recupero y su tesis duplicada no se publica."""

    class _T:
        id = 7
        version = 3
        status = "final"

    def generate_and_lose_fence(self, db, ticker, force_new_version=False, phase_callback=None):
        _steal_run(run_container["id"])
        return _T()

    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="FENCEOK")
    run_container = {"id": run.id}
    monkeypatch.setattr(ThesisService, "generate", generate_and_lose_fence)
    jobs.run_thesis_job(run.id)

    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        assert stored.status == "running" and stored.attempt == 2
        assert stored.result_payload is None


def test_fenced_failure_cannot_overwrite_recovered_run(monkeypatch):
    """El manejador de fallos de un intento cercado tampoco pisa el estado
    del nuevo dueno (ni failed ni error_class)."""

    def generate_and_fail_fenced(self, db, ticker, force_new_version=False, phase_callback=None):
        _steal_run(run_container["id"])
        raise ValueError("boom")

    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="FENCEFAIL")
    run_container = {"id": run.id}
    monkeypatch.setattr(ThesisService, "generate", generate_and_fail_fenced)
    with pytest.raises(ValueError):
        jobs.run_thesis_job(run.id)

    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        assert stored.status == "running" and stored.attempt == 2
        assert stored.error_class is None


def _steal_at_terminal_update(armed, run_container):
    """Hook before_cursor_execute: roba el run (attempt+1) en el instante en
    que el UPDATE terminal de workflow_runs YA se esta ejecutando: el hueco
    exacto entre check y write del fencing lectura-escritura. Si la sesion del
    job retiene locks (sqlite, flujo antiguo con lecturas previas), el robo
    falla y se traga: el assert final sobre el estado robado es el que manda.
    """
    from sqlalchemy import event

    from app.core.database import engine

    def hook(conn, cursor, statement, parameters, context, executemany):
        if armed["on"] and not armed["done"] and statement.lstrip().upper().startswith("UPDATE WORKFLOW_RUNS"):
            armed["done"] = True
            try:
                _steal_run(run_container["id"])
            except Exception:  # noqa: BLE001 - lock ambiental sqlite, ver docstring
                pass

    event.listen(engine, "before_cursor_execute", hook)
    return hook


def test_atomic_success_close_survives_steal_during_terminal_update(monkeypatch):
    """Regresion: robo del run DURANTE la escritura terminal de exito. El
    UPDATE condicional por attempt observa el robo (rowcount=0) y aborta con
    rollback; el fencing de lectura previa lo pisaba."""

    class _T:
        id = 7
        version = 3
        status = "final"

    def fake_generate(self, db, ticker, force_new_version=False, phase_callback=None):
        armed["on"] = True
        return _T()

    armed = {"on": False, "done": False}
    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="ATOMOK")
    run_container = {"id": run.id}
    monkeypatch.setattr(ThesisService, "generate", fake_generate)
    hook = _steal_at_terminal_update(armed, run_container)
    from sqlalchemy import event

    from app.core.database import engine

    try:
        jobs.run_thesis_job(run.id)
    finally:
        event.remove(engine, "before_cursor_execute", hook)

    assert armed["done"] is True
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        assert stored.status == "running" and stored.attempt == 2
        assert stored.result_payload is None


def test_atomic_failure_close_survives_steal_during_terminal_update(monkeypatch):
    """Regresion: mismo robo DURANTE la escritura terminal de fallo. El
    intento cercado no escribe ni failed ni error_class."""

    def generate_and_fail(self, db, ticker, force_new_version=False, phase_callback=None):
        armed["on"] = True
        raise ValueError("boom")

    armed = {"on": False, "done": False}
    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="ATOMFAIL")
    run_container = {"id": run.id}
    monkeypatch.setattr(ThesisService, "generate", generate_and_fail)
    hook = _steal_at_terminal_update(armed, run_container)
    from sqlalchemy import event

    from app.core.database import engine

    try:
        with pytest.raises(ValueError):
            jobs.run_thesis_job(run.id)
    finally:
        event.remove(engine, "before_cursor_execute", hook)

    assert armed["done"] is True
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        assert stored.status == "running" and stored.attempt == 2
        assert stored.error_class is None


def test_recovery_caps_repeated_interrupted_deliveries(monkeypatch):
    """Un ticker que tumba al worker en cada intento no re-bota cada 6 h para
    siempre: al agotar MAX_ATTEMPTS el run queda en failed honesto."""
    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="CRASHLOOP")
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        stored.status = "running"
        stored.attempt = jobs.MAX_ATTEMPTS
        stored.started_at = stored.created_at - jobs.RUNNING_LEASE - timedelta(minutes=1)
        db.commit()

    jobs.run_thesis_job(run.id)

    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        assert stored.status == "failed"
        assert stored.error_class == "RecoverableRunningState"
        assert stored.finished_at is not None


def test_latest_generation_is_tenant_scoped(monkeypatch):
    from uuid import uuid4

    from app.models import Tenant

    with SessionLocal() as db:
        tenant = Tenant(external_id=f"recovery-{uuid4().hex}", name="Recovery tenant")
        db.add(tenant)
        db.commit()
        tenant_id = tenant.id
    run, _ = _enqueue_without_dispatch(monkeypatch, tenant_id=tenant_id, user_id="user")
    try:
        with SessionLocal() as db:
            db.info["tenant_id"] = tenant_id
            assert jobs.latest_generation(db, "AAPL").id == run.id
        with SessionLocal() as db:
            db.info["tenant_id"] = tenant_id + 100000
            assert jobs.latest_generation(db, "AAPL") is None
    finally:
        with SessionLocal() as db:
            db.query(WorkflowRun).filter_by(id=run.id).delete()
            db.query(Tenant).filter_by(id=tenant_id).delete()
            db.commit()


def test_worker_enriches_unknown_company_before_generation(monkeypatch):
    from app.models import Company

    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="ZZWORKER")
    monkeypatch.setattr(
        "app.services.company_enrichment_service.CompanyEnrichmentService.enrich",
        lambda *args, **kwargs: False,
    )

    def generate(self, db, ticker, **kwargs):
        assert db.scalar(select(Company).where(Company.ticker == ticker)) is not None
        return _fake_generate()(self, db, ticker, **kwargs)

    monkeypatch.setattr(ThesisService, "generate", generate)
    jobs.run_thesis_job(run.id)
    with SessionLocal() as db:
        assert db.get(WorkflowRun, run.id).status == "succeeded"
        db.query(Company).filter_by(ticker="ZZWORKER").delete()
        db.commit()


def test_scheduler_recovers_jobs_without_browser():
    from app.workers.scheduler import build_scheduler

    scheduler = build_scheduler(background=True)
    job = scheduler.get_job("thesis_dispatch_recovery")
    assert job is not None
    assert job.func is jobs.reconcile_thesis_dispatches
    assert job.trigger.interval == timedelta(minutes=1)


def test_queued_publish_gap_is_recovered_without_post(monkeypatch):
    run, _ = _enqueue_without_dispatch(monkeypatch, ticker="LOST")
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        stored.updated_at = stored.created_at - jobs.DISPATCH_RECHECK - timedelta(minutes=1)
        db.commit()
    sent = []
    import app.workers.dramatiq_app as workers

    monkeypatch.setattr(workers.generate_thesis_job, "send", lambda run_id: sent.append(run_id))
    assert jobs.reconcile_thesis_dispatches()["redispatched"] == 1
    assert sent == [run.id]


def test_concurrent_enqueue_with_distinct_click_ids_creates_one_active_run(monkeypatch):
    """Dos sesiones pasan la comprobacion de activo a la vez (carrera): solo un
    run activo y una sola publicacion."""
    sent = []
    monkeypatch.setattr(jobs, "_dispatch_run", lambda run: sent.append(run.id))
    db1, db2 = SessionLocal(), SessionLocal()
    try:
        real_latest = jobs.latest_generation
        calls = {"n": 0}

        def racing_latest(db, ticker, **kwargs):
            result = real_latest(db, ticker, **kwargs)
            calls["n"] += 1
            if calls["n"] == 1 and kwargs.get("active_only"):
                # La otra sesion inserta y confirma justo despues de esta comprobacion.
                other, created = jobs.enqueue_generation(db2, "AAPL", False, "click2")
                assert created
            return result

        monkeypatch.setattr(jobs, "latest_generation", racing_latest)
        run1, created1 = jobs.enqueue_generation(db1, "AAPL", False, "click1")
        run1_id = run1.id
    finally:
        db1.close()
        db2.close()
    check = SessionLocal()
    try:
        active = check.scalars(
            select(WorkflowRun).where(WorkflowRun.workflow_name == jobs.WORKFLOW_NAME)
        ).all()
        assert len(active) == 1
        assert created1 is False and run1_id == active[0].id
        assert len(sent) == 1
    finally:
        check.close()


def test_tracked_worker_refreshes_sec_before_stored_only_generation(monkeypatch):
    import sys
    from types import SimpleNamespace

    calls = []
    async def refresh(db, company):
        calls.append("sec")
        return {"status": "ok", "provider": "SEC", "facts_imported": 5}
    monkeypatch.setitem(sys.modules, "app.services.tracked_financial_refresh", SimpleNamespace(refresh_free_financials=refresh))
    def generate(self, db, ticker, force_new_version=False, phase_callback=None, **kwargs):
        calls.append("thesis")
        assert kwargs["stored_evidence_only"] is True
        assert kwargs["refresh_receipt"]["status"] == "ok"
        return _fake_generate()(self, db, ticker, force_new_version, phase_callback)
    monkeypatch.setattr(ThesisService, "generate", generate)
    run, _ = _enqueue_without_dispatch(monkeypatch)
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        stored.input_payload = {**stored.input_payload, "tracked": True}
        db.commit()
    jobs.run_thesis_job(run.id)
    with SessionLocal() as db:
        stored = db.get(WorkflowRun, run.id)
        assert calls == ["sec", "thesis"]
        assert stored.status == "succeeded"
        assert stored.result_payload["financial_refresh"]["facts_imported"] == 5
