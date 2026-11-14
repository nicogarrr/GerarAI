"""Actores con una sola referencia en la suite: reconcile_alert_analyses,
dispatch_earnings_reminders, recompute_management_alignment y
retry_deferred_tenant_ibkr_connections.

Contratos fijados (mismo patron que test_worker_alert_actors.py y
test_worker_uncovered_actors.py):
- lease liberado y sesion cerrada en ok, lease_held y error;
- error de servicio = rollback + payload estructurado via _handle_actor_error;
- el reintento diferido de IBKR solo reprograma tenants con receipt
  not_ready reciente y usa el actor dedicado cuando el ajuste lo activa.

Run from data-engine/:
    pytest tests/test_worker_reminder_reconcile_actors.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core import database as database_module
from app.services import alert_analysis_service, earnings_reminders, outbound_alerts
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    e = SimpleNamespace(
        db=MagicMock(),
        lease="LEASE",
        released=[],
        rolled=[],
        handled=[],
        session_error=None,
        acquire_error=None,
    )
    e.db.info = {"tenant_id": 1}

    def session(tenant, user):
        if e.session_error:
            raise e.session_error
        return e.db

    def acquire(key, **kw):
        if e.acquire_error:
            raise e.acquire_error
        return e.lease

    def handle(actor, exc, **ctx):
        e.handled.append((actor, exc, ctx))
        return {"status": "error", "actor": actor, "error": {"type": type(exc).__name__}}

    monkeypatch.setattr(worker, "_session", session)
    monkeypatch.setattr(worker, "acquire_job_lease", acquire)
    monkeypatch.setattr(worker, "release_job_lease", lambda key, lease, **kw: e.released.append((key, lease)))
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    monkeypatch.setattr(worker, "_rollback", lambda db: e.rolled.append(db))
    monkeypatch.setattr(worker, "_handle_actor_error", handle)
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    return e


# --- reconcile_alert_analyses -------------------------------------------------


def test_reconcile_analyses_ok(env, monkeypatch):
    monkeypatch.setattr(alert_analysis_service, "reconcile_missing_analyses", lambda db: {"queued": 3})

    out = worker.reconcile_alert_analyses.fn(tenant_id=1, user_id="u")

    assert out == {"actor": "reconcile_alert_analyses", "status": "ok", "queued": 3}
    assert env.released == [("reconcile_alert_analyses:1", "LEASE")]
    env.db.close.assert_called_once_with()


def test_reconcile_analyses_lease_held(env, monkeypatch):
    env.lease = None
    called = []
    monkeypatch.setattr(alert_analysis_service, "reconcile_missing_analyses", lambda db: called.append(db))

    out = worker.reconcile_alert_analyses.fn(tenant_id=1, user_id="u")

    assert out["reason"] == "lease_held"
    assert called == []
    env.db.close.assert_called_once_with()


def test_reconcile_analyses_lease_lanza_cierra_sesion(env, monkeypatch):
    env.acquire_error = ConnectionError("redis down")
    called = []
    monkeypatch.setattr(alert_analysis_service, "reconcile_missing_analyses", lambda db: called.append(db))

    with pytest.raises(ConnectionError):
        worker.reconcile_alert_analyses.fn(tenant_id=1, user_id="u")

    assert called == []
    env.db.close.assert_called_once_with()


def test_reconcile_analyses_error_rollback_lease_y_cierre(env, monkeypatch):
    boom = ValueError("fila corrupta")
    def fail(db):
        raise boom

    monkeypatch.setattr(alert_analysis_service, "reconcile_missing_analyses", fail)

    out = worker.reconcile_alert_analyses.fn(tenant_id=1, user_id="u")

    assert out["status"] == "error"
    assert env.rolled == [env.db]
    assert env.released == [("reconcile_alert_analyses:1", "LEASE")]
    env.db.close.assert_called_once_with()


# --- dispatch_earnings_reminders ----------------------------------------------


def test_earnings_reminders_ok_mapea_stats(env, monkeypatch):
    monkeypatch.setattr(earnings_reminders, "emit_earnings_reminders", lambda db: {"created": 2, "existing": 1})
    monkeypatch.setattr(outbound_alerts, "dispatch_pending", lambda db: {"redispatched": 1, "errors": []})

    out = worker.dispatch_earnings_reminders.fn(tenant_id=1, user_id="u")

    assert out == {
        "status": "ok", "actor": "dispatch_earnings_reminders",
        "created": 2, "existing": 1, "redispatched": 1, "errors": [],
    }
    assert env.released == [("dispatch_earnings_reminders:1", "LEASE")]
    env.db.close.assert_called_once_with()


def test_earnings_reminders_lease_held_no_despacha(env, monkeypatch):
    env.lease = None
    called = []
    monkeypatch.setattr(earnings_reminders, "emit_earnings_reminders", lambda db: called.append(db))
    monkeypatch.setattr(outbound_alerts, "dispatch_pending", lambda db: called.append(db))

    out = worker.dispatch_earnings_reminders.fn(tenant_id=1, user_id="u")

    assert out["reason"] == "lease_held"
    assert called == []
    env.db.close.assert_called_once_with()


def test_earnings_reminders_error_libera_todo(env, monkeypatch):
    boom = RuntimeError("smtp caido")
    def fail(db):
        raise boom

    monkeypatch.setattr(earnings_reminders, "emit_earnings_reminders", fail)

    out = worker.dispatch_earnings_reminders.fn(tenant_id=1, user_id="u")

    assert out["status"] == "error"
    assert env.rolled == [env.db]
    assert env.released == [("dispatch_earnings_reminders:1", "LEASE")]
    env.db.close.assert_called_once_with()


# --- recompute_management_alignment -------------------------------------------


def test_management_alignment_company_concreta(env, monkeypatch):
    company = SimpleNamespace(id=9, ticker="ABC")
    env.db.scalars.return_value = [company]  # select(Company).where(id == 9) es iterable directo
    recomputed = []
    monkeypatch.setattr("app.services.management_alignment.recompute_alignment", lambda db, c: recomputed.append(c))

    out = worker.recompute_management_alignment.fn(tenant_id=1, user_id="u", company_id=9)

    assert out == {"actor": "recompute_management_alignment", "status": "ok", "companies": 1}
    assert recomputed == [company]
    env.db.commit.assert_called_once_with()
    env.db.close.assert_called_once_with()


def test_management_alignment_error_rollback(env, monkeypatch):
    env.db.scalars.return_value = [SimpleNamespace(id=9, ticker="ABC")]
    boom = KeyError("snapshot")

    def fail(db, c):
        raise boom

    monkeypatch.setattr("app.services.management_alignment.recompute_alignment", fail)

    out = worker.recompute_management_alignment.fn(tenant_id=1, user_id="u", company_id=9)

    assert out["status"] == "error"
    assert env.rolled == [env.db]
    env.db.close.assert_called_once_with()


# --- retry_deferred_tenant_ibkr_connections ------------------------------------


def _patch_admin(monkeypatch, ids):
    admin = MagicMock()
    admin.scalars.return_value.all.return_value = sorted(ids)
    admin.__enter__.return_value = admin
    admin.__exit__.return_value = False
    monkeypatch.setattr(database_module, "SessionLocal", lambda: admin)
    return admin


def test_retry_deferred_solo_tenants_not_ready_recientes(env, monkeypatch):
    _patch_admin(monkeypatch, {2})
    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(ibkr_dedicated_sync_enabled=False))
    monkeypatch.setattr(worker, "tenant_contexts", lambda: [(1, "one"), (2, "two"), (3, "three")])
    sent_default, sent_dedicated = [], []
    monkeypatch.setattr(worker.sync_one_tenant_ibkr, "send", lambda *a: sent_default.append(a))
    monkeypatch.setattr(worker.sync_one_tenant_ibkr_dedicated, "send", lambda *a: sent_dedicated.append(a))

    out = worker.retry_deferred_tenant_ibkr_connections.fn()

    assert out == {"scheduled": 1}
    assert sent_default == [(2, "two")]
    assert sent_dedicated == []


def test_retry_deferred_usa_actor_dedicado_si_el_ajuste_lo_activa(env, monkeypatch):
    _patch_admin(monkeypatch, {3})
    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(ibkr_dedicated_sync_enabled=True))
    monkeypatch.setattr(worker, "tenant_contexts", lambda: [(3, "three")])
    sent_default, sent_dedicated = [], []
    monkeypatch.setattr(worker.sync_one_tenant_ibkr, "send", lambda *a: sent_default.append(a))
    monkeypatch.setattr(worker.sync_one_tenant_ibkr_dedicated, "send", lambda *a: sent_dedicated.append(a))

    out = worker.retry_deferred_tenant_ibkr_connections.fn()

    assert out == {"scheduled": 1}
    assert sent_dedicated == [(3, "three")]
    assert sent_default == []


def test_retry_deferred_error_estructurado(env, monkeypatch):
    admin = MagicMock()
    boom = ConnectionError("pg caido")
    admin.__enter__.return_value = admin
    admin.__exit__.return_value = False
    admin.scalars.side_effect = boom
    monkeypatch.setattr(database_module, "SessionLocal", lambda: admin)

    out = worker.retry_deferred_tenant_ibkr_connections.fn()

    assert out["status"] == "error"
    assert env.handled and env.handled[0][1] is boom
