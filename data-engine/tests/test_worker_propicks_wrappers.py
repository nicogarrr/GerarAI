"""run_propicks_funnel, freeze_propicks_snapshot e ingest_spy_daily (happy path y error).

Sin bug encontrado: se fija el mapeo de payloads, el bootstrap idempotente
del snapshot mensual tras el run del embudo, el caso «sin snapshot» (None ->
month None/passed 0) y el error clasificado con rollback y sesion cerrada.

Run from data-engine/:
    pytest tests/test_worker_propicks_wrappers.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    e = SimpleNamespace(db=MagicMock(), rolled=[], handled=[])
    e.db.info = {"tenant_id": 1}

    def handle(actor, exc, **ctx):
        e.handled.append((actor, exc, ctx))
        return {"status": "error", "actor": actor, "error": {"type": type(exc).__name__}}

    monkeypatch.setattr(worker, "_session", lambda tenant, user: e.db)
    monkeypatch.setattr(worker, "_rollback", lambda db: e.rolled.append(db))
    monkeypatch.setattr(worker, "_handle_actor_error", handle)
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    return e


def test_funnel_ok_bootstrap_snapshot(env, monkeypatch):
    monkeypatch.setattr(
        "app.services.propicks_funnel_service.execute_run",
        lambda db, top_n: SimpleNamespace(id=11, passed_count=7, top_n=top_n),
    )
    monkeypatch.setattr(
        "app.services.propicks_snapshot_service.freeze_monthly_snapshot",
        lambda db: SimpleNamespace(month="2026-11"),
    )

    out = worker.run_propicks_funnel.fn(tenant_id=1, user_id="u")

    assert out == {
        "actor": "run_propicks_funnel", "run_id": 11, "passed_count": 7,
        "top_n": 100, "snapshot_month": "2026-11",
    }
    env.db.close.assert_called_once_with()


def test_funnel_error_rollback_y_cierre(env, monkeypatch):
    boom = ConnectionError("proveedor")
    def fail(db, top_n):
        raise boom

    monkeypatch.setattr("app.services.propicks_funnel_service.execute_run", fail)

    out = worker.run_propicks_funnel.fn(tenant_id=1, user_id="u")

    assert out["status"] == "error"
    assert env.rolled == [env.db]
    env.db.close.assert_called_once_with()


def test_freeze_snapshot_ok(env, monkeypatch):
    monkeypatch.setattr(
        "app.services.propicks_snapshot_service.freeze_monthly_snapshot",
        lambda db: SimpleNamespace(month="2026-11", passed_count=12),
    )

    out = worker.freeze_propicks_snapshot.fn(tenant_id=1, user_id="u")

    assert out == {"actor": "freeze_propicks_snapshot", "month": "2026-11", "passed_count": 12}
    env.db.close.assert_called_once_with()


def test_freeze_snapshot_sin_fila(env, monkeypatch):
    monkeypatch.setattr(
        "app.services.propicks_snapshot_service.freeze_monthly_snapshot",
        lambda db: None,
    )

    out = worker.freeze_propicks_snapshot.fn(tenant_id=1, user_id="u")

    assert out == {"actor": "freeze_propicks_snapshot", "month": None, "passed_count": 0}


def test_spy_daily_ok_y_error(env, monkeypatch):
    monkeypatch.setattr(
        "app.services.propicks_track_record_service.ingest_spy_prices",
        lambda db: {"status": "ok", "rows": 3},
    )

    out = worker.ingest_spy_daily.fn(tenant_id=1, user_id="u")

    assert out == {"actor": "ingest_spy_daily", "status": "ok", "rows": 3}
    env.db.close.assert_called_once_with()

    boom = TimeoutError("yahoo")
    def fail(db):
        raise boom

    monkeypatch.setattr("app.services.propicks_track_record_service.ingest_spy_prices", fail)

    out = worker.ingest_spy_daily.fn(tenant_id=1, user_id="u")

    assert out["status"] == "error"
    assert env.rolled == [env.db]
