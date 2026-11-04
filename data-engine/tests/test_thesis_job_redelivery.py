"""Re-entrega del MISMO mensaje de dramatiq tras la muerte del worker.

El broker Redis de dramatiq solo devuelve a la cola un mensaje sin ack cuando
el worker que lo tenia deja de dar latido (reinicio del contenedor en un
despliegue, OOM, SIGKILL), y lo devuelve con el MISMO message_id. Esa
re-entrega se descartaba por el lease fresco del intento muerto y el run se
quedaba en "running" (bloqueando nuevas generaciones del ticker) hasta que
caducaba el lease de 6 h.
"""

from datetime import UTC, datetime

import pytest
from dramatiq.middleware import CurrentMessage

from app.core.database import SessionLocal, init_db
from app.models.entities import WorkflowRun, WorkflowStepRun
from app.seed import seed
from app.services import thesis_job_service as jobs
from app.services.thesis_service import ThesisService


class _WorkerKilled(BaseException):
    """El proceso muere a mitad de la generacion: nada de la app lo captura."""


class _Msg:
    def __init__(self, message_id: str) -> None:
        self.message_id = message_id
        self.options: dict = {}


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


def _deliver(monkeypatch, run_id: int, message_id: str | None) -> None:
    message = _Msg(message_id) if message_id else None
    monkeypatch.setattr(CurrentMessage, "get_current_message", staticmethod(lambda: message))
    jobs.run_thesis_job(run_id)


def _enqueue(monkeypatch, ticker: str) -> int:
    import app.workers.dramatiq_app as workers

    monkeypatch.setattr(workers.generate_thesis_job, "send", lambda run_id: None)
    with SessionLocal() as db:
        run, _ = jobs.enqueue_generation(db, ticker, False, None)
        return run.id


def _generate_ok(self, db, ticker, force_new_version=False, phase_callback=None, **kwargs):
    for phase in jobs.THESIS_PHASES:
        if phase_callback:
            phase_callback(phase)

    class _T:
        id = 11
        version = 1
        status = "final"

    return _T()


def _generate_killed(self, db, ticker, force_new_version=False, phase_callback=None, **kwargs):
    if phase_callback:
        phase_callback(jobs.THESIS_PHASES[0])
    raise _WorkerKilled()


def _kill_during_generation(monkeypatch, run_id: int, message_id: str) -> None:
    monkeypatch.setattr(ThesisService, "generate", _generate_killed)
    with pytest.raises(_WorkerKilled):
        _deliver(monkeypatch, run_id, message_id)


def _run(run_id: int) -> WorkflowRun:
    with SessionLocal() as db:
        run = db.get(WorkflowRun, run_id)
        assert run is not None
        db.expunge(run)
        return run


def test_same_message_redelivered_after_worker_death_recovers_now(monkeypatch):
    run_id = _enqueue(monkeypatch, "REDELIV")
    _kill_during_generation(monkeypatch, run_id, "msg-1")
    dead = _run(run_id)
    assert dead.status == "running"
    assert dead.attempt == 1
    # El lease del intento muerto sigue fresco (minutos, no 6 h).
    assert datetime.now(UTC) - jobs._utc(dead.started_at) < jobs.RUNNING_LEASE

    monkeypatch.setattr(ThesisService, "generate", _generate_ok)
    _deliver(monkeypatch, run_id, "msg-1")

    recovered = _run(run_id)
    assert recovered.status == "succeeded"
    # La recuperacion consume un intento, igual que la del lease expirado.
    assert recovered.attempt == 2


def test_other_message_with_fresh_lease_is_still_dropped(monkeypatch):
    """Una entrega DISTINTA (duplicado del reconciler, doble envio) mientras
    el intento vive sigue cayendo por lease fresco: sin doble generacion."""
    run_id = _enqueue(monkeypatch, "OTHERMSG")
    _kill_during_generation(monkeypatch, run_id, "msg-1")
    calls = {"n": 0}

    def counting(self, *args, **kwargs):
        calls["n"] += 1
        return _generate_ok(self, *args, **kwargs)

    monkeypatch.setattr(ThesisService, "generate", counting)
    _deliver(monkeypatch, run_id, "msg-2")
    _deliver(monkeypatch, run_id, None)

    assert calls["n"] == 0
    still = _run(run_id)
    assert still.status == "running"
    assert still.attempt == 1


def test_repeated_worker_deaths_end_in_terminal_failure(monkeypatch):
    """Un ticker que tumba al worker en cada intento no re-bota para siempre:
    cada re-entrega consume un intento y al tope el run falla honestamente."""
    run_id = _enqueue(monkeypatch, "OOMLOOP")
    for _ in range(jobs.MAX_ATTEMPTS):
        _kill_during_generation(monkeypatch, run_id, "msg-1")
    assert _run(run_id).attempt == jobs.MAX_ATTEMPTS

    monkeypatch.setattr(ThesisService, "generate", _generate_ok)
    _deliver(monkeypatch, run_id, "msg-1")

    failed = _run(run_id)
    assert failed.status == "failed"
    assert failed.error_class == "RecoverableRunningState"
    assert failed.finished_at is not None


def test_stale_delivery_of_previous_owner_does_not_steal_run(monkeypatch):
    """Tras recuperar con otro mensaje, una re-entrega del mensaje VIEJO no
    roba el run al dueno actual (su lease es fresco y no es su mensaje)."""
    run_id = _enqueue(monkeypatch, "OLDOWNER")
    _kill_during_generation(monkeypatch, run_id, "msg-1")
    _kill_during_generation(monkeypatch, run_id, "msg-1")  # recupera y vuelve a morir
    assert _run(run_id).attempt == 2
    with SessionLocal() as db:
        run = db.get(WorkflowRun, run_id)
        assert run is not None
        payload = dict(run.input_payload or {})
        payload["delivery_message_id"] = "msg-9"  # otro mensaje reclamo el intento vivo
        run.input_payload = payload
        db.commit()
    monkeypatch.setattr(ThesisService, "generate", _generate_ok)
    _deliver(monkeypatch, run_id, "msg-1")

    still = _run(run_id)
    assert still.status == "running"
    assert still.attempt == 2
