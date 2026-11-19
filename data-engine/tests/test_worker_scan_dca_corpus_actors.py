"""scan_form144_watchlist (stats, lease, N/D nunca inventado), pasada DCA
con run-log (ok, disabled, lease, error que cierra la corrida) e
ingest_letters_corpus (corpus libre con dedupe, lease)."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.corpus_ingestion_service as cis
import app.services.dca_run_log as drl
import app.services.dca_signal_service as dss
import app.services.form144_monitor as f144
import app.services.plan_proactivity as pp
from app.models.entities import Base
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    leases = {"held": False}
    monkeypatch.setattr(worker, "acquire_job_lease",
                        lambda *a, **k: None if leases["held"] else "L")
    released = []
    monkeypatch.setattr(worker, "release_job_lease",
                        lambda name, lease, **k: released.append(name))
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    monkeypatch.setattr(worker, "get_settings",
                        lambda: SimpleNamespace(dca_evaluation_enabled=True))
    return SimpleNamespace(db=db, released=released, leases=leases)


# --- scan_form144_watchlist -------------------------------------------------

def test_form144_ok_propaga_metricas(env, monkeypatch):
    monkeypatch.setattr(f144, "scan", lambda db_, **kw: {
        "status": "ok", "tickers_scanned": 3, "filings_seen": 5,
        "filings_new": 2, "filings_unparsed": 1, "filings_rejected": 0,
        "errors": []})
    out = worker.scan_form144_watchlist.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["tickers_scanned"] == 3
    assert out["filings_unparsed"] == 1  # lo no parseable queda N/D, nunca inventado
    assert env.released == ["scan_form144_watchlist:1"]


def test_form144_lease_ocupado_salta(env):
    env.leases["held"] = True
    out = worker.scan_form144_watchlist.fn(tenant_id=1, user_id="u")
    assert out["reason"] == "lease_held" and out["status"] == "skipped"


def test_form144_error_devuelve_payload(env, monkeypatch):
    monkeypatch.setattr(f144, "scan",
                        lambda db_, **kw: (_ for _ in ()).throw(ValueError("sec")))
    out = worker.scan_form144_watchlist.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["actor"] == "scan_form144_watchlist"
    assert env.released == ["scan_form144_watchlist:1"]  # lease liberado en error


# --- evaluate_dca_signals (via _run_dca_evaluation) --------------------------

def test_dca_ok_con_run_log_y_revision_ahorro(env, monkeypatch):
    monkeypatch.setattr(dss, "evaluate_watchlist",
                        lambda db_, skip_closed_markets: {"evaluated": 4})
    started, finished = [], []
    monkeypatch.setattr(drl, "start_run",
                        lambda db_, trigger: started.append(trigger) or "RUN")
    monkeypatch.setattr(drl, "finish_run",
                        lambda db_, run, **kw: finished.append(kw))
    monkeypatch.setattr(pp, "review_savings_plan", lambda db_: {"reviewed": True})
    out = worker.evaluate_dca_signals.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["evaluated"] == 4
    assert out["savings_plan_review"] == {"reviewed": True}
    assert started == ["scheduler"] and finished[0]["summary"]["evaluated"] == 4


def test_dca_disabled_salta(env, monkeypatch):
    import app.core.config as config

    monkeypatch.setattr(config, "get_settings",
                        lambda: SimpleNamespace(dca_evaluation_enabled=False))
    out = worker.evaluate_dca_signals.fn(tenant_id=1, user_id="u")
    assert out == {"status": "skipped", "actor": "evaluate_dca_signals",
                   "reason": "disabled"}


def test_dca_lease_ocupado_salta(env):
    env.leases["held"] = True
    out = worker.evaluate_dca_signals.fn(tenant_id=1, user_id="u")
    assert out["reason"] == "lease_held"


def test_dca_error_cierra_la_corrida_con_error(env, monkeypatch):
    monkeypatch.setattr(dss, "evaluate_watchlist",
                        lambda db_, skip_closed_markets: (_ for _ in ()).throw(
                            RuntimeError("precios caidos")))
    monkeypatch.setattr(drl, "start_run", lambda db_, trigger: "RUN")
    finished = []
    monkeypatch.setattr(drl, "finish_run",
                        lambda db_, run, **kw: finished.append(kw))
    out = worker.evaluate_dca_signals.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error"
    assert "RuntimeError" in finished[0]["error"]  # la corrida nunca queda abierta
    assert env.released == ["evaluate_dca_signals:1"]


# --- ingest_letters_corpus ---------------------------------------------------

def test_corpus_ok(env, monkeypatch):
    monkeypatch.setattr(cis, "ingest_free_corpus",
                        lambda db_: {"status": "ok", "ingested": 7, "duplicates": 2})
    out = worker.ingest_letters_corpus.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["ingested"] == 7
    assert out["actor"] == "ingest_letters_corpus"
    assert env.released == ["ingest_letters_corpus:1"]


def test_corpus_lease_ocupado_salta(env):
    env.leases["held"] = True
    assert worker.ingest_letters_corpus.fn(tenant_id=1)["reason"] == "lease_held"


def test_corpus_error_devuelve_payload(env, monkeypatch):
    monkeypatch.setattr(cis, "ingest_free_corpus",
                        lambda db_: (_ for _ in ()).throw(ValueError("red")))
    out = worker.ingest_letters_corpus.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["actor"] == "ingest_letters_corpus"
