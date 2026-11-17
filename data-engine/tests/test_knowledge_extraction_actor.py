"""Actor de extraccion de principios y utilidades de mensaje de dramatiq_app."""

import sys
import types
from types import SimpleNamespace

import pytest

from app.workers import dramatiq_app as da


def _fn(actor):
    return getattr(actor, "fn", actor)


class FakeDb:
    def __init__(self, job=None, document=None):
        self.job, self.document = job, document
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def get(self, model, _id):
        return self.job if getattr(model, "__name__", "") == "ProcessingJob" else self.document

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def _job():
    return SimpleNamespace(
        id=7, entity_id=3, status="queued", started_at=None, completed_at=None,
        error=None, result=None, progress_current=0, progress_total=0,
    )


class _Interrupt(BaseException):
    pass


@pytest.fixture
def env(monkeypatch):
    from app.services import knowledge_library_service as kls

    state = SimpleNamespace(db=None, outcome=None, handled=[])

    class Service:
        async def extract_principle_batches(self, db, document, progress=None):
            if progress:
                progress(1, 2)
            if isinstance(state.outcome, BaseException):
                raise state.outcome
            return dict(state.outcome)

    monkeypatch.setattr(kls, "KnowledgeLibraryService", Service)
    monkeypatch.setattr(da, "_session", lambda tenant_id, user_id: state.db)
    monkeypatch.setattr(da, "_run", lambda coroutine: _drive(coroutine))
    monkeypatch.setattr(
        da, "_handle_actor_error",
        lambda actor, exc, **ctx: state.handled.append((actor, exc, ctx)) or {"status": "failed"},
    )
    return state


def _drive(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as stop:
        return stop.value
    raise AssertionError("la corrutina no deberia suspenderse")


def _call(job_id=7):
    return _fn(da.extract_knowledge_principles)(job_id, tenant_id=1, user_id="u")


def test_completed_job_records_result_and_progress(env):
    job = _job()
    env.db = FakeDb(job, SimpleNamespace(id=3))
    env.outcome = {"principles": [SimpleNamespace(id=11), SimpleNamespace(id=12)], "budget_stopped": False}
    out = _call()
    assert out["status"] == "ok" and job.status == "completed"
    assert job.result["principle_ids"] == [11, 12]
    assert (job.progress_current, job.progress_total) == (1, 2)
    assert env.db.closed and job.started_at is not None and job.completed_at is not None


def test_budget_stop_is_partial_not_completed(env):
    job = _job()
    env.db = FakeDb(job, SimpleNamespace(id=3))
    env.outcome = {"principles": [], "budget_stopped": True}
    _call()
    assert job.status == "partial"


def test_missing_job_is_handled_without_touching_a_job(env):
    env.db = FakeDb(None, None)
    assert _call() == {"status": "failed"}
    assert env.db.rollbacks == 1 and env.db.closed
    assert "was not found" in str(env.handled[0][1])


def test_missing_document_marks_job_failed_without_diagnostic(env):
    job = _job()
    env.db = FakeDb(job, None)
    _call()
    assert job.status == "failed" and "was not found" in job.error
    assert job.result is None
    assert env.db.rollbacks == 1


def test_invalid_output_stores_bounded_diagnostic_after_rollback(env):
    from app.llm.errors import StructuredOutputError

    job = _job()
    env.db = FakeDb(job, SimpleNamespace(id=3))
    exc = StructuredOutputError("vacio")
    exc.diagnostic = {"batch_index": 2, "batch_count": 3, "finish_reason": "length"}
    env.outcome = exc
    _call()
    assert job.status == "failed"
    assert job.result == {"error_diagnostic": exc.diagnostic}
    assert "lote 2/3" in job.error and "length" in job.error
    assert env.db.rollbacks == 1


def test_non_dict_diagnostic_is_ignored(env):
    job = _job()
    env.db = FakeDb(job, SimpleNamespace(id=3))
    exc = ValueError("x")
    exc.diagnostic = "no-es-dict"
    env.outcome = exc
    _call()
    assert job.result is None and job.status == "failed"


def test_time_limit_marks_job_failed_and_reraises(env, monkeypatch):
    class TimeLimitExceeded(BaseException):
        pass

    module = types.ModuleType("dramatiq.middleware.time_limit")
    module.TimeLimitExceeded = TimeLimitExceeded
    monkeypatch.setitem(sys.modules, "dramatiq.middleware.time_limit", module)
    job = _job()
    env.db = FakeDb(job, SimpleNamespace(id=3))
    env.outcome = TimeLimitExceeded()
    with pytest.raises(TimeLimitExceeded):
        _call()
    assert job.status == "failed" and "tiempo máximo" in job.error
    assert env.db.rollbacks == 1 and env.db.closed


def test_time_limit_before_job_is_known_still_reraises(env, monkeypatch):
    class TimeLimitExceeded(BaseException):
        pass

    module = types.ModuleType("dramatiq.middleware.time_limit")
    module.TimeLimitExceeded = TimeLimitExceeded
    monkeypatch.setitem(sys.modules, "dramatiq.middleware.time_limit", module)

    class Boom:
        def __format__(self, spec):
            raise TimeLimitExceeded()

    env.db = FakeDb(None, None)
    with pytest.raises(TimeLimitExceeded):
        _fn(da.extract_knowledge_principles)(Boom(), tenant_id=1, user_id="u")
    assert env.db.rollbacks == 1 and env.db.closed


def test_batch_status_and_enqueue_mark_key():
    assert da._batch_status(2, [{"e": 1}]) == "partial"
    assert da._batch_status(0, [{"e": 1}]) == "error"
    assert da._batch_status(3, []) == "ok"
    assert da._enqueue_mark_key("job", ("a", "b")) == "coalesce-enq:job:a:b"


def _message(monkeypatch, message=None, boom=False):
    def get_current_message():
        if boom:
            raise RuntimeError("sin broker")
        return message

    monkeypatch.setattr(da, "CurrentMessage", SimpleNamespace(get_current_message=get_current_message))


def test_retry_or_delayed_probe(monkeypatch):
    _message(monkeypatch, boom=True)
    assert da._current_message_is_retry_or_delayed() is False
    _message(monkeypatch, None)
    assert da._current_message_is_retry_or_delayed() is False
    _message(monkeypatch, SimpleNamespace(options={"retries": 1}))
    assert da._current_message_is_retry_or_delayed() is True
    _message(monkeypatch, SimpleNamespace(options={"eta": 5}))
    assert da._current_message_is_retry_or_delayed() is True
    _message(monkeypatch, SimpleNamespace(options={}))
    assert da._current_message_is_retry_or_delayed() is False


def test_current_message_retries(monkeypatch):
    _message(monkeypatch, boom=True)
    assert da._current_message_retries() == 0
    _message(monkeypatch, SimpleNamespace(options={"retries": 3}))
    assert da._current_message_retries() == 3
    _message(monkeypatch, SimpleNamespace(options={"retries": "x"}))
    assert da._current_message_retries() == 0
    _message(monkeypatch, SimpleNamespace(options={}))
    assert da._current_message_retries() == 0


def test_current_message_age(monkeypatch):
    _message(monkeypatch, boom=True)
    assert da._current_message_age_seconds() is None
    _message(monkeypatch, None)
    assert da._current_message_age_seconds() is None
    _message(monkeypatch, SimpleNamespace(options={"retries": 1}, message_timestamp=1))
    assert da._current_message_age_seconds() is None
    _message(monkeypatch, SimpleNamespace(options={}, message_timestamp=None))
    assert da._current_message_age_seconds() is None
    monkeypatch.setattr(da.time, "time", lambda: 100.0)
    _message(monkeypatch, SimpleNamespace(options={}, message_timestamp=90_000))
    assert da._current_message_age_seconds() == 10.0
    _message(monkeypatch, SimpleNamespace(options={}, message_timestamp=200_000))
    assert da._current_message_age_seconds() == 0.0


def test_rollback_swallows_a_failing_rollback():
    class Broken:
        def rollback(self):
            raise RuntimeError("conexion perdida")

    assert da._rollback(Broken()) is None
    db = FakeDb()
    da._rollback(db)
    assert db.rollbacks == 1
