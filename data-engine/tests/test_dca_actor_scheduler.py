"""Actor evaluate_dca_signals y su job diario en el scheduler."""

from __future__ import annotations

from typing import Any

from app.workers import dramatiq_app
from app.workers import scheduler as sched


def test_actor_is_registered_on_default_queue():
    actor = dramatiq_app.evaluate_dca_signals
    assert actor.actor_name == "evaluate_dca_signals"
    assert actor.queue_name == "default"


def test_scheduler_registers_dca_job_after_official_closes(monkeypatch):
    seen: dict[str, tuple[str, dict, Any]] = {}
    orig = sched._register

    def spy(scheduler, func, trigger, *, job_id, **kw):
        orig(scheduler, func, trigger, job_id=job_id, **kw)
        seen[job_id] = (trigger, dict(kw), func)

    monkeypatch.setattr(sched, "_register", spy)
    sched.build_scheduler(background=True)
    trigger, kwargs, func = seen["dca_signals_daily"]
    assert trigger == "cron"
    assert (kwargs["day_of_week"], kwargs["hour"], kwargs["minute"]) == ("mon-fri", 23, 15)
    closes = seen["official_closes_daily"][1]
    assert (kwargs["hour"], kwargs["minute"]) > (closes["hour"], closes["minute"])
    assert func.func is sched.enqueue_for_all_tenants
    assert func.args == (dramatiq_app.evaluate_dca_signals,)


def test_actor_skips_when_evaluation_disabled(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("DCA_EVALUATION_ENABLED", "false")
    get_settings.cache_clear()
    try:
        out = dramatiq_app.evaluate_dca_signals.fn(1, "u-1")
    finally:
        monkeypatch.delenv("DCA_EVALUATION_ENABLED")
        get_settings.cache_clear()
    assert out == {"status": "skipped", "actor": "evaluate_dca_signals", "reason": "disabled"}


def test_actor_evaluates_even_with_alerts_disabled(monkeypatch):
    """Con DCA_ALERTS_ENABLED=false la evaluacion diaria sigue corriendo.

    Los avisos y la evaluacion son cosas distintas: sin evaluacion las
    insignias 1X-4X de la watchlist se quedan vacias o viejas. El aviso ya lo
    filtra el servicio (``evaluate_watchlist``) con ``dca_alerts_enabled``.
    """
    from app.core.config import get_settings

    calls: list[str] = []

    monkeypatch.setattr("app.services.plan_proactivity.review_savings_plan", lambda db: {"plan_exists": False, "new_in_app_alerts": 0})

    class FakeDb:
        info = {}
        def commit(self):
            pass
        def close(self):
            calls.append("close")

    monkeypatch.setenv("DCA_ALERTS_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: FakeDb())
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda name, **kw: calls.append(name) or "tok")
    monkeypatch.setattr(dramatiq_app, "release_job_lease", lambda name, token, **kw: calls.append(f"release:{token}"))
    monkeypatch.setattr(
        "app.services.dca_signal_service.evaluate_watchlist",
        lambda db: calls.append("evaluate") or {"evaluated": 2, "alerted": [], "alerts_enabled": False},
    )
    try:
        out = dramatiq_app.evaluate_dca_signals.fn(7, "u-1")
    finally:
        monkeypatch.delenv("DCA_ALERTS_ENABLED")
        get_settings.cache_clear()
    assert out["status"] == "ok" and out["evaluated"] == 2
    assert calls == ["evaluate_dca_signals:7", "evaluate", "release:tok", "close"]


def test_actor_takes_lease_and_runs_service(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr("app.services.plan_proactivity.review_savings_plan", lambda db: {"plan_exists": False, "new_in_app_alerts": 0})

    class FakeDb:
        info = {}
        def commit(self):
            pass
        def close(self):
            calls.append("close")

    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: FakeDb())
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda name, **kw: calls.append(name) or "tok")
    monkeypatch.setattr(dramatiq_app, "release_job_lease", lambda name, token, **kw: calls.append(f"release:{token}"))
    monkeypatch.setattr(
        "app.services.dca_signal_service.evaluate_watchlist",
        lambda db: {"evaluated": 3, "alerted": []},
    )
    out = dramatiq_app.evaluate_dca_signals.fn(7, "u-1")
    assert out["actor"] == "evaluate_dca_signals" and out["evaluated"] == 3
    assert calls == ["evaluate_dca_signals:7", "release:tok", "close"]


def test_actor_lease_held(monkeypatch):
    monkeypatch.setattr("app.services.plan_proactivity.review_savings_plan", lambda db: {"plan_exists": False, "new_in_app_alerts": 0})

    class FakeDb:
        info = {}
        def commit(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: FakeDb())
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda name, **kw: None)
    out = dramatiq_app.evaluate_dca_signals.fn(7, "u-1")
    assert out["reason"] == "lease_held"
