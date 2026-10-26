"""PR3: guard LLM por job de tesis. Solo fixtures: sin red, sin Redis, sin LLM real."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.llm.run_guard import InMemoryCounterStore, LLMGuardAbort, current_guard
from app.models.entities import WorkflowRun
from app.services import thesis_job_service as jobs
from app.services.thesis_service import ThesisService
from tests.test_thesis_jobs import _enqueue_without_dispatch, _fake_generate


def _settings(**kw):
    base = dict(
        llm_run_guard_max_posts=8,
        llm_run_guard_max_tokens_per_request=4000,
        llm_run_guard_max_total_output_tokens=22400,
        llm_run_guard_allowed_hosts="opencode.ai",
        llm_run_guard_allowed_models="deepseek-v4.1-flash",
        llm_run_guard_window_seconds=7 * 24 * 3600,
        redis_url="redis://127.0.0.1:1/0",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _run(age=timedelta(0)):
    return SimpleNamespace(id=41, created_at=datetime.now(UTC) - age)


def test_disabled_by_default_returns_none():
    assert jobs.build_run_guard(_run(), _settings(llm_run_guard_max_posts=0)) is None


def test_run_id_has_no_attempt_and_is_stable_across_retries():
    store = InMemoryCounterStore()
    g1 = jobs.build_run_guard(_run(), _settings(), store=store)
    g2 = jobs.build_run_guard(_run(), _settings(), store=store)
    assert g1.run_id == g2.run_id == "thesis:41"
    assert g1.store is g2.store


def test_run_older_than_window_fails_closed():
    with pytest.raises(LLMGuardAbort) as e:
        jobs.build_run_guard(_run(timedelta(days=7, seconds=1)), _settings(), store=InMemoryCounterStore())
    assert e.value.reason == "run_guard_window_expired"


def test_misconfigured_limits_or_missing_hosts_fail_closed():
    for kw in ({"llm_run_guard_allowed_hosts": ""}, {"llm_run_guard_allowed_models": ""},
               {"llm_run_guard_max_tokens_per_request": 0}, {"llm_run_guard_max_total_output_tokens": 0}):
        with pytest.raises(LLMGuardAbort) as e:
            jobs.build_run_guard(_run(), _settings(**kw), store=InMemoryCounterStore())
        assert e.value.reason == "guard_misconfigured"


@pytest.fixture(autouse=True)
def _db():
    from app.core.database import SessionLocal, init_db
    from app.models.entities import WorkflowStepRun
    from app.seed import seed

    init_db()
    seed()
    yield
    db = SessionLocal()
    for model in (WorkflowStepRun, WorkflowRun):
        db.query(model).delete()
    db.commit()
    db.close()


def _patch_guard_settings(monkeypatch, **kw):
    real = jobs.get_settings()
    for k, v in vars(_settings(**kw)).items():
        if k != "redis_url":
            monkeypatch.setattr(real, k, v, raising=False)


def test_job_does_not_activate_guard_by_default(monkeypatch):
    seen = []

    def generate(self, db, ticker, force_new_version=False, phase_callback=None, **kw):
        seen.append(current_guard())
        return _fake_generate()(self, db, ticker, force_new_version, phase_callback)

    monkeypatch.setattr(ThesisService, "generate", generate)
    run, _ = _enqueue_without_dispatch(monkeypatch)
    jobs.run_thesis_job(run.id)
    assert seen == [None]


def test_job_activates_guard_when_enabled_and_resets_after(monkeypatch):
    seen = []
    store = InMemoryCounterStore()

    def generate(self, db, ticker, force_new_version=False, phase_callback=None, **kw):
        seen.append(current_guard())
        return _fake_generate()(self, db, ticker, force_new_version, phase_callback)

    monkeypatch.setattr(ThesisService, "generate", generate)
    _patch_guard_settings(monkeypatch)
    orig = jobs.build_run_guard
    monkeypatch.setattr(jobs, "build_run_guard", lambda r, s: orig(r, s, store=store))
    run, _ = _enqueue_without_dispatch(monkeypatch)
    jobs.run_thesis_job(run.id)
    assert seen[0] is not None and seen[0].run_id == f"thesis:{run.id}"
    assert seen[0].store is store
    assert current_guard() is None


def test_job_fails_closed_before_generate_when_window_invalid(monkeypatch):
    called = []
    monkeypatch.setattr(ThesisService, "generate", lambda *a, **k: called.append(1))
    _patch_guard_settings(monkeypatch, llm_run_guard_window_seconds=0)
    run, _ = _enqueue_without_dispatch(monkeypatch)
    try:
        jobs.run_thesis_job(run.id)
    except Exception:
        pass
    assert called == []
    assert current_guard() is None
