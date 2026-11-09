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
        lambda db, **kw: calls.append("evaluate") or {"evaluated": 2, "alerted": [], "alerts_enabled": False},
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
    seen: list[dict] = []

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
        lambda db, **kw: seen.append(kw) or {"evaluated": 3, "alerted": []},
    )
    out = dramatiq_app.evaluate_dca_signals.fn(7, "u-1")
    # La pasada diaria salta los tickers con su bolsa cerrada ese día.
    assert seen == [{"skip_closed_markets": True}]
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


class _FakeRedis:
    """Redis minimo en memoria para las sondas de coalescencia (set NX EX, get, delete, eval CAS)."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, *keys):
        removed = 0
        for key in keys:
            removed += self.store.pop(key, None) is not None
        return removed

    def eval(self, script, numkeys, key, token):  # compare-and-delete
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


def test_premarket_job_registered_separate_from_close_confirmation(monkeypatch):
    """dca_signals_premarket (12:30 UTC) y dca_signals_daily (23:15 UTC) encolan actores distintos."""
    seen: dict[str, tuple[str, dict, Any]] = {}
    orig = sched._register

    def spy(scheduler, func, trigger, *, job_id, **kw):
        orig(scheduler, func, trigger, job_id=job_id, **kw)
        seen[job_id] = (trigger, dict(kw), func)

    monkeypatch.setattr(sched, "_register", spy)
    sched.build_scheduler(background=True)
    trigger, kwargs, func = seen["dca_signals_premarket"]
    assert trigger == "cron"
    assert (kwargs["day_of_week"], kwargs["hour"], kwargs["minute"]) == ("mon-fri", 12, 30)
    assert func.func is sched.enqueue_for_all_tenants
    assert func.args == (dramatiq_app.evaluate_dca_signals_live,)
    _, daily_kwargs, daily_func = seen["dca_signals_daily"]
    assert (daily_kwargs["hour"], daily_kwargs["minute"]) == (23, 15)
    assert daily_func.args == (dramatiq_app.evaluate_dca_signals,)
    # Politicas de coalescencia con claves separadas: nunca comparten semaforo.
    policies = dramatiq_app._COALESCE_POLICIES
    assert "evaluate_dca_signals" in policies and "evaluate_dca_signals_live" in policies


def test_live_claim_does_not_suppress_close_confirmation(monkeypatch):
    """Con el claim live FRESCO (pasada premercado con exito), la confirmacion
    de cierre de las 23:15 UTC reclama su propia clave y TRABAJA; el claim
    live solo suprime otra live."""
    fake = _FakeRedis()
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: fake)
    ran: list[str] = []
    monkeypatch.setattr(
        dramatiq_app,
        "_run_dca_evaluation",
        lambda actor, tenant_id, user_id, review_savings: ran.append(actor) or {"status": "ok"},
    )

    out_live = dramatiq_app.evaluate_dca_signals_live.fn(7, "u-1")
    assert out_live == {"status": "ok"}
    assert fake.get("coalesce:evaluate_dca_signals_live:7")  # claim fresco de la premercado

    out_close = dramatiq_app.evaluate_dca_signals.fn(7, "u-1")
    assert out_close == {"status": "ok"}  # NO skipped: la confirmacion corre
    assert ran == ["evaluate_dca_signals_live", "evaluate_dca_signals"]

    # El mecanismo es real: una segunda live con claim fresco SI se salta,
    # pero la confirmacion de cierre sigue sin verse afectada por esa clave.
    out_live2 = dramatiq_app.evaluate_dca_signals_live.fn(7, "u-1")
    assert out_live2["status"] == "skipped" and out_live2["reason"] == "fresh_or_running"
    assert fake.get("coalesce:evaluate_dca_signals:7")


def test_live_enqueue_mark_does_not_suppress_close_enqueue(monkeypatch):
    """coalesced_send: una live en cola (marca coalesce-enq live) NO suprime
    el encolado de la confirmacion de cierre, solo el de otra live."""
    fake = _FakeRedis()
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: fake)
    sent: list[str] = []
    monkeypatch.setattr(dramatiq_app.evaluate_dca_signals_live, "send", lambda *a, **k: sent.append("live") or "m-live")
    monkeypatch.setattr(dramatiq_app.evaluate_dca_signals, "send", lambda *a, **k: sent.append("close") or "m-close")

    first = dramatiq_app.coalesced_send(dramatiq_app.evaluate_dca_signals_live, 7, "u-1")
    dup = dramatiq_app.coalesced_send(dramatiq_app.evaluate_dca_signals_live, 7, "u-1")
    assert first == "m-live" and dup is None  # una copia en vuelo por clave

    close = dramatiq_app.coalesced_send(dramatiq_app.evaluate_dca_signals, 7, "u-1")
    assert close == "m-close"  # la 23:15 UTC encola aunque la live siga en cola
    assert sent == ["live", "close"]


def test_run_dca_evaluation_error_path_records_and_reports(monkeypatch):
    """La excepcion dentro de la evaluacion hace rollback, cierra el run con
    error y devuelve el resultado estructurado (camino de _handle_actor_error)."""
    from app.workers import dramatiq_app as dapp

    class FakeDb:
        info: dict = {}

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    finished: list[dict] = []
    monkeypatch.setattr(dapp, "_session", lambda tenant_id, user_id: FakeDb())
    monkeypatch.setattr(dapp, "acquire_job_lease", lambda name, **kw: "tok")
    monkeypatch.setattr(dapp, "release_job_lease", lambda name, token, **kw: None)

    from app.services import dca_run_log

    monkeypatch.setattr(dca_run_log, "start_run", lambda db, origin: object())
    monkeypatch.setattr(dca_run_log, "finish_run", lambda db, run, **kw: finished.append(kw))

    def boom(db, **kw):
        raise ValueError("permanente")

    monkeypatch.setattr("app.services.dca_signal_service.evaluate_watchlist", boom)
    out = dapp._run_dca_evaluation("evaluate_dca_signals_live", 7, "u-1", review_savings=False)
    assert out["actor"] == "evaluate_dca_signals_live" and out["status"] == "error"
    assert out["error"]["type"] == "ValueError" and "permanente" in out["error"]["message"]
    assert finished and "error" in finished[0]
