"""Actores de alertas: el lease se libera siempre, no hay doble ejecución y
un fallo no deja el lease retenido ni la sesión abierta.

Run from data-engine/:
    pytest tests/test_worker_alert_actors.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    e = SimpleNamespace(db=MagicMock(), lease="LEASE", released=[], acquired=[], rolled=[], session_error=None)

    def session(tenant, user):
        if e.session_error:
            raise e.session_error
        return e.db

    def acquire(key, **kw):
        e.acquired.append((key, kw["ttl_seconds"]))
        return e.lease

    monkeypatch.setattr(worker, "_session", session)
    monkeypatch.setattr(worker, "acquire_job_lease", acquire)
    monkeypatch.setattr(worker, "release_job_lease", lambda key, lease, **kw: e.released.append((key, lease)))
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    monkeypatch.setattr(worker, "_rollback", lambda db: e.rolled.append(db))
    return e


# --- reconcile_alert_deliveries -------------------------------------------

def _patch_notifications(monkeypatch, stats, pending, boom=None):
    from app.services import notification_service, outbound_alerts

    class NS:
        def reconcile_stale_deliveries(self, db, tenant_id=None):
            if boom:
                raise boom
            return stats

    monkeypatch.setattr(notification_service, "NotificationService", NS)
    monkeypatch.setattr(outbound_alerts, "dispatch_pending", lambda db: pending)


def test_reconcile_merges_pending_and_stale_counts_and_caps_errors(env, monkeypatch):
    stats = {"candidates": 2, "redispatched": 1, "errors": [f"e{i}" for i in range(30)]}
    _patch_notifications(monkeypatch, stats, {"candidates": 3, "redispatched": 2, "errors": ["p"]})
    out = worker.reconcile_alert_deliveries.fn(tenant_id=5, user_id="u")
    assert out["status"] == "ok" and out["candidates"] == 5 and out["redispatched"] == 3
    assert len(out["errors"]) == 20  # acotado
    assert env.acquired == [("reconcile_alert_deliveries:5", 600)]
    assert env.released == [("reconcile_alert_deliveries:5", "LEASE")]
    env.db.close.assert_called_once()


def test_reconcile_skips_when_lease_held_and_does_not_release_what_it_never_got(env, monkeypatch):
    env.lease = None
    _patch_notifications(monkeypatch, {}, {})
    out = worker.reconcile_alert_deliveries.fn(tenant_id=5, user_id="u")
    assert out == {"status": "skipped", "actor": "reconcile_alert_deliveries", "reason": "lease_held"}
    assert env.released == []
    env.db.close.assert_called_once()


def test_reconcile_failure_releases_lease_and_closes_session(env, monkeypatch):
    _patch_notifications(monkeypatch, {}, {}, boom=ValueError("db caída"))
    out = worker.reconcile_alert_deliveries.fn(tenant_id=5, user_id="u")
    assert out["status"] == "error" and out["error"]["context"] == {"tenant_id": 5}
    assert env.released and env.released[0][0] == "reconcile_alert_deliveries:5"
    env.db.close.assert_called_once()


def test_reconcile_inactive_tenant_takes_no_lease(env, monkeypatch):
    env.session_error = ValueError("Active tenant 5 was not found")
    out = worker.reconcile_alert_deliveries.fn(tenant_id=5, user_id="u")
    assert out["status"] == "error"
    assert env.acquired == [] and env.released == []


# --- analyze_tracked_news_alert / dispatch_tracked_news_alerts -----------------

def test_analyze_alert_runs_once_per_lease_and_releases(env, monkeypatch):
    from app.services import alert_analysis_service
    monkeypatch.setattr(alert_analysis_service, "analyze_alert", lambda db, alert_id: {"status": "ok", "alert_id": alert_id})
    out = worker.analyze_tracked_news_alert.fn(9, tenant_id=1, user_id="u")
    assert out == {"status": "ok", "alert_id": 9}
    assert env.acquired == [("analyze_tracked_news_alert:1:9", 300)]
    assert env.released == [("analyze_tracked_news_alert:1:9", "LEASE")]
    env.db.close.assert_called_once()


def test_analyze_alert_lease_held_skips_and_closes(env):
    env.lease = None
    out = worker.analyze_tracked_news_alert.fn(9, tenant_id=1, user_id="u")
    assert out == {"status": "skipped", "reason": "lease_held", "alert_id": 9}
    env.db.close.assert_called_once()
    assert env.released == []


def test_analyze_alert_failure_rolls_back_and_still_releases(env, monkeypatch):
    from app.services import alert_analysis_service

    def boom(db, alert_id):
        raise ValueError("análisis roto")

    monkeypatch.setattr(alert_analysis_service, "analyze_alert", boom)
    out = worker.analyze_tracked_news_alert.fn(9, tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["error"]["context"] == {"alert_id": 9}
    assert env.rolled == [env.db] and env.released
    env.db.close.assert_called_once()


def test_analyze_alert_lease_backend_error_closes_session_and_raises(env, monkeypatch):
    def broken(key, **kw):
        raise ConnectionError("redis")

    monkeypatch.setattr(worker, "acquire_job_lease", broken)
    with pytest.raises(ConnectionError):
        worker.analyze_tracked_news_alert.fn(9, tenant_id=1, user_id="u")
    env.db.close.assert_called_once()


def test_dispatch_lease_held_is_skipped(env):
    env.lease = None
    out = worker.dispatch_tracked_news_alerts.fn(tenant_id=1, user_id="u")
    assert out == {"actor": "dispatch_tracked_news_alerts", "status": "skipped", "reason": "lease_held"}
    env.db.close.assert_called_once()


def test_dispatch_requeues_pending_analyses_and_reports_count(env, monkeypatch):
    from app.services import asts_spacex_signal, tracked_news_alerts

    monkeypatch.setattr(tracked_news_alerts, "evaluate", lambda db: {"status": "ok", "created": 2})
    monkeypatch.setattr(asts_spacex_signal, "evaluate", lambda db: {"fired": False})
    env.db.scalars.return_value.all.return_value = [SimpleNamespace(alert_id=11), SimpleNamespace(alert_id=12)]
    sent = []
    monkeypatch.setattr(worker.analyze_tracked_news_alert, "send",
                        lambda alert_id, **kw: sent.append((alert_id, kw)))
    out = worker.dispatch_tracked_news_alerts.fn(tenant_id=1, user_id="u")
    assert out["analysis_enqueued"] == 2 and out["created"] == 2 and out["asts_spacex_signal"] == {"fired": False}
    assert sent == [(11, {"tenant_id": 1, "user_id": "u"}), (12, {"tenant_id": 1, "user_id": "u"})]
    assert env.released == [("dispatch_tracked_news_alerts:1", "LEASE")]


def test_dispatch_failure_rolls_back_and_releases(env, monkeypatch):
    from app.services import tracked_news_alerts

    def boom(db):
        raise ValueError("evaluate roto")

    monkeypatch.setattr(tracked_news_alerts, "evaluate", boom)
    out = worker.dispatch_tracked_news_alerts.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error"
    assert env.rolled == [env.db] and env.released
    env.db.close.assert_called_once()
