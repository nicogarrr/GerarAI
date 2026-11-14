"""Actores de dramatiq_app sin cobertura: watchdogs de colas/fuentes,
scan 13D/13G, estimaciones de prensa, shares por clase y el job SOTP.

Contratos fijados aqui (mismo patron que test_worker_alert_actors.py):
- el lease se libera SIEMPRE (ok, lease_held ajeno, error) y la sesion se cierra;
- un fallo del servicio pasa por _handle_actor_error y hace _rollback;
- ingest_class_shares_outstanding clasifica sus errores como el resto de
  actores: un ValueError permanente de _session NO debe reventar crudo
  (dramatiq lo reintentaria dos veces y lo mandaria a dead-letter sin
  registro estructurado): devuelve el payload de error de _handle_actor_error.

Run from data-engine/:
    pytest tests/test_worker_uncovered_actors.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import class_filer_eps_service, queue_watchdog, schedule13dg_monitor, source_health_watchdog
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    """Sesion/lease/rollback falsos; los actores no tocan Redis ni Postgres."""
    e = SimpleNamespace(
        db=MagicMock(),
        lease="LEASE",
        released=[],
        acquired=[],
        rolled=[],
        session_error=None,
        acquire_error=None,
        handled=[],
    )

    def session(tenant, user):
        if e.session_error:
            raise e.session_error
        return e.db

    def acquire(key, **kw):
        if e.acquire_error:
            raise e.acquire_error
        e.acquired.append((key, kw["ttl_seconds"]))
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
    # La coalescencia es fail-open sin Redis; lo fijamos para que no dependa
    # del entorno del runner.
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    return e


# --- dispatch_queue_watchdog -----------------------------------------------


def test_queue_watchdog_ok_libera_lease_y_cierra(env, monkeypatch):
    seen = {}

    def emit(db):
        seen["db"] = db
        return {"queues": 2}

    monkeypatch.setattr(queue_watchdog, "emit_queue_stuck_alerts", emit)

    out = worker.dispatch_queue_watchdog.fn(tenant_id=1, user_id="u")

    assert out == {"status": "ok", "actor": "dispatch_queue_watchdog", "queues": 2}
    assert seen["db"] is env.db
    assert env.acquired == [("dispatch_queue_watchdog:1", 120)]
    assert env.released == [("dispatch_queue_watchdog:1", "LEASE")]
    env.db.close.assert_called_once_with()


def test_queue_watchdog_lease_held_no_trabaja(env, monkeypatch):
    env.lease = None
    called = []
    monkeypatch.setattr(queue_watchdog, "emit_queue_stuck_alerts", lambda db: called.append(db))

    out = worker.dispatch_queue_watchdog.fn(tenant_id=1, user_id="u")

    assert out == {"status": "skipped", "actor": "dispatch_queue_watchdog", "reason": "lease_held"}
    assert called == []
    env.db.close.assert_called_once_with()


def test_queue_watchdog_error_rollback_lease_y_cierre(env, monkeypatch):
    boom = KeyError("redis")
    def fail(db):
        raise boom

    monkeypatch.setattr(queue_watchdog, "emit_queue_stuck_alerts", fail)

    out = worker.dispatch_queue_watchdog.fn(tenant_id=1, user_id="u")

    assert out["status"] == "error"
    assert env.handled and env.handled[0][1] is boom
    assert env.rolled == [env.db]
    assert env.released == [("dispatch_queue_watchdog:1", "LEASE")]
    env.db.close.assert_called_once_with()


# --- dispatch_source_health_watchdog ---------------------------------------


def test_source_health_watchdog_ok(env, monkeypatch):
    monkeypatch.setattr(source_health_watchdog, "emit_source_health_alerts", lambda db: {"sources": 1})

    out = worker.dispatch_source_health_watchdog.fn(tenant_id=2, user_id="u")

    assert out == {"status": "ok", "actor": "dispatch_source_health_watchdog", "sources": 1}
    assert env.released == [("dispatch_source_health_watchdog:2", "LEASE")]
    env.db.close.assert_called_once_with()


def test_source_health_watchdog_lease_held(env, monkeypatch):
    env.lease = None
    called = []
    monkeypatch.setattr(source_health_watchdog, "emit_source_health_alerts", lambda db: called.append(db))

    out = worker.dispatch_source_health_watchdog.fn(tenant_id=2, user_id="u")

    assert out["reason"] == "lease_held"
    assert called == []
    env.db.close.assert_called_once_with()


def test_source_health_watchdog_error_libera_todo(env, monkeypatch):
    boom = RuntimeError("registry")
    def fail(db):
        raise boom

    monkeypatch.setattr(source_health_watchdog, "emit_source_health_alerts", fail)

    out = worker.dispatch_source_health_watchdog.fn(tenant_id=2, user_id="u")

    assert out["status"] == "error"
    assert env.rolled == [env.db]
    assert env.released == [("dispatch_source_health_watchdog:2", "LEASE")]
    env.db.close.assert_called_once_with()


# --- scan_schedule13dg_watchlist -------------------------------------------

_STATS = {
    "status": "ok",
    "tickers_scanned": 3,
    "filings_seen": 5,
    "filings_new": 1,
    "filings_unparsed": 0,
    "filings_rejected": 0,
    "errors": [],
}


def test_scan13dg_ok_mapea_metricas(env, monkeypatch):
    kwargs = {}

    def scan(db, **kw):
        kwargs.update(kw)
        return dict(_STATS)

    monkeypatch.setattr(schedule13dg_monitor, "scan", scan)

    out = worker.scan_schedule13dg_watchlist.fn(tenant_id=4, user_id="u", lookback=40, max_new_fetches=10)

    assert out["status"] == "ok"
    assert out["tickers_scanned"] == 3 and out["filings_new"] == 1
    assert kwargs == {"tenant_id": 4, "lookback": 40, "max_new_fetches": 10}
    assert env.released == [("scan_schedule13dg_watchlist:4", "LEASE")]
    env.db.close.assert_called_once_with()


def test_scan13dg_lease_held_cierra_sesion(env, monkeypatch):
    env.lease = None
    called = []
    monkeypatch.setattr(schedule13dg_monitor, "scan", lambda db, **kw: called.append(db))

    out = worker.scan_schedule13dg_watchlist.fn(tenant_id=4, user_id="u")

    assert out["reason"] == "lease_held"
    assert called == []
    env.db.close.assert_called_once_with()


def test_scan13dg_lease_lanza_cierra_sesion(env, monkeypatch):
    env.acquire_error = ConnectionError("redis down")

    out = worker.scan_schedule13dg_watchlist.fn(tenant_id=4, user_id="u")

    assert out["status"] == "error"
    env.db.close.assert_called_once_with()


# --- collect_analyst_estimates ----------------------------------------------


def test_collect_estimates_sin_tenant_skip(env):
    out = worker.collect_analyst_estimates.fn(tenant_id=None, user_id="u")

    assert out == {"actor": "collect_analyst_estimates", "status": "skipped", "reason": "sin tenant"}
    env.db.close.assert_called_once_with()


def _scalars_then(*pages):
    """db.scalars(...) devuelve cada pagina (.all()) en orden de llamada."""
    mocks = []
    for page in pages:
        m = MagicMock()
        m.all.return_value = page
        mocks.append(m)
    return mocks


def test_collect_estimates_ok_una_empresa(env, monkeypatch):
    watch = SimpleNamespace(symbol="abc")
    company = SimpleNamespace(ticker="ABC")
    env.db.scalars.side_effect = _scalars_then([watch], [company])
    monkeypatch.setattr(
        "app.services.analyst_press_estimates.refresh_press_estimates",
        lambda db, c, tenant, **kw: {"stored": [1, 2]},
    )
    monkeypatch.setattr("app.services.guidance_backfill.ensure_backfill", lambda *a, **kw: None)
    monkeypatch.setattr("app.services.estimate_accuracy.freeze_consensus", lambda *a, **kw: None)
    monkeypatch.setattr("app.services.own_consensus.build_company_consensus", lambda *a, **kw: {"n": 1})

    out = worker.collect_analyst_estimates.fn(tenant_id=7, user_id="u")

    assert out == {"actor": "collect_analyst_estimates", "status": "ok", "stored": {"ABC": 2}}
    env.db.close.assert_called_once_with()


def test_collect_estimates_empresa_falla_no_para_al_resto(env, monkeypatch):
    watch = SimpleNamespace(symbol="abc")
    company = SimpleNamespace(ticker="ABC")
    env.db.scalars.side_effect = _scalars_then([watch], [company])
    boom = ValueError("payload malo")

    def fail(db, c, tenant, **kw):
        raise boom

    monkeypatch.setattr("app.services.analyst_press_estimates.refresh_press_estimates", fail)

    out = worker.collect_analyst_estimates.fn(tenant_id=7, user_id="u")

    assert out["status"] == "ok"
    assert out["stored"] == {"ABC": "ValueError"}
    env.db.rollback.assert_called()
    env.db.close.assert_called_once_with()


# --- ingest_class_shares_outstanding ----------------------------------------


def _company(ticker):
    return SimpleNamespace(ticker=ticker, cik="0001")


def test_ingest_class_shares_resultados_por_empresa(env, monkeypatch):
    outcomes = {
        "AAA": SimpleNamespace(written=True, skipped_reason=None),
        "BBB": SimpleNamespace(written=False, skipped_reason="no_cik"),
    }

    def backfill(db, company, *, cik):
        if company.ticker == "CCC":
            raise KeyError("ECSO")
        return outcomes[company.ticker]

    monkeypatch.setattr(class_filer_eps_service, "class_cover_candidates", lambda db: [_company(t) for t in ("AAA", "BBB", "CCC")])
    monkeypatch.setattr(class_filer_eps_service, "backfill_class_shares_outstanding", backfill)

    out = worker.ingest_class_shares_outstanding.fn(tenant_id=3, user_id="u")

    assert out == {
        "actor": "ingest_class_shares_outstanding",
        "status": "ok",
        "results": {"AAA": "ok", "BBB": "skipped:no_cik", "CCC": "error"},
    }
    assert env.rolled == [env.db]
    env.db.close.assert_called_once_with()


def test_ingest_class_shares_error_de_sesion_es_estructurado(env):
    """Un ValueError permanente de _session no debe reventar crudo: igual que
    el resto de actores, pasa por _handle_actor_error (payload error, sin
    reintentos muertos a dead-letter)."""
    env.session_error = ValueError("tenant_id and user_id are required for background jobs")

    out = worker.ingest_class_shares_outstanding.fn(tenant_id=None, user_id=None)

    assert out["status"] == "error"
    assert out["actor"] == "ingest_class_shares_outstanding"
    assert env.handled and isinstance(env.handled[0][1], ValueError)


def test_ingest_class_shares_error_en_candidatas_tambien_clasificado(env, monkeypatch):
    boom = ValueError("tabla ausente")
    def fail(db):
        raise boom

    monkeypatch.setattr(class_filer_eps_service, "class_cover_candidates", fail)

    out = worker.ingest_class_shares_outstanding.fn(tenant_id=3, user_id="u")

    assert out["status"] == "error"
    assert env.handled and env.handled[0][1] is boom
    env.db.close.assert_called_once_with()


# --- generate_sotp_agents_job ------------------------------------------------


def test_sotp_agents_job_delega_en_el_servicio(monkeypatch):
    runs = []
    monkeypatch.setattr("app.services.sotp_agents_job.run_job", lambda run_id: runs.append(run_id))

    worker.generate_sotp_agents_job.fn(123)

    assert runs == [123]


def test_sotp_agents_job_sin_reintentos_y_cola_thesis():
    actor = worker.generate_sotp_agents_job
    assert actor.queue_name == "thesis"
    assert actor.options["max_retries"] == 0
    assert actor.options["time_limit"] == 300_000
