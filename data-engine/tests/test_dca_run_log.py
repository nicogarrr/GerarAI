"""Registro de ejecuciones DCA: la UI distingue nunca ejecutado / fallo / omitido."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, inspect

import main
from app.core.database import SessionLocal, init_db
from app.models import DcaEvaluationRun
from app.services import dca_run_log, dca_signal_service
from app.workers import dramatiq_app

from .test_dca_signals_api import SYMBOLS, client  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def _clean_runs():
    init_db()
    with SessionLocal() as db:
        db.execute(delete(DcaEvaluationRun))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(DcaEvaluationRun))
        db.commit()


def _item(client, symbol="DCATST"):
    body = client.get("/api/watchlist/dca-signals").json()
    return body, next(i for i in body["items"] if i["symbol"] == symbol)


def test_never_run_is_reported_as_never_run_not_as_failure(client):
    client.post("/api/watchlist", json={"symbol": "DCATST"})
    body, item = _item(client)
    assert body["last_run"] is None
    assert item["state"] is None
    assert item["evaluation_status"] == "never_run"


def test_manual_run_is_recorded_and_symbol_is_evaluated(client):
    client.post("/api/watchlist", json={"symbol": "DCATST"})
    assert client.post("/api/watchlist/dca-signals/evaluate").status_code == 200
    body, item = _item(client)
    run = body["last_run"]
    assert run["status"] == "ok" and run["trigger"] == "manual"
    assert run["evaluated"] >= 1 and run["errors"] == 0 and run["finished_at"] is not None
    assert item["evaluation_status"] == "evaluated"


def test_failed_run_marks_symbols_without_state_as_job_failed(client, monkeypatch):
    client.post("/api/watchlist", json={"symbol": "DCATST"})

    def boom(db):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(dca_signal_service, "evaluate_watchlist", boom)
    failing = TestClient(main.app, raise_server_exceptions=False)
    assert failing.post("/api/watchlist/dca-signals/evaluate").status_code == 500
    body, item = _item(client)
    assert body["last_run"]["status"] == "error"
    assert "yahoo down" in body["last_run"]["error"]
    assert item["evaluation_status"] == "job_failed"
    assert "yahoo down" in item["evaluation_reason"]


def test_per_symbol_errors_and_skips_are_visible(client, monkeypatch):
    client.post("/api/watchlist", json={"symbol": "DCATST"})
    client.post("/api/watchlist", json={"symbol": "DCAOFF"})

    def fake(db):
        return {
            "tracked": 2, "evaluated": 0, "alerted": [],
            "skipped": [{"symbol": "DCAOFF", "reason": "datos_desactualizados", "last_price_date": "2026-01-02"}],
            "errors": [{"symbol": "DCATST", "error": "HTTPError"}],
            "params_version": "nico-v1", "alerts_enabled": False,
        }

    monkeypatch.setattr(dca_signal_service, "evaluate_watchlist", fake)
    assert client.post("/api/watchlist/dca-signals/evaluate").status_code == 200
    body, tst = _item(client, "DCATST")
    _, off = _item(client, "DCAOFF")
    assert body["last_run"]["status"] == "ok" and body["last_run"]["errors"] == 1
    assert (tst["evaluation_status"], tst["evaluation_reason"]) == ("job_failed", "HTTPError")
    assert (off["evaluation_status"], off["evaluation_reason"]) == ("skipped", "datos_desactualizados")


def test_stale_running_row_is_reported_as_interrupted():
    with SessionLocal() as db:
        db.add(DcaEvaluationRun(
            trigger="scheduler", status="running", detail={},
            started_at=datetime.now(UTC) - timedelta(hours=2),
        ))
        db.commit()
        payload = dca_run_log.run_payload(dca_run_log.latest_run(db))
    assert payload["status"] == "interrupted"
    assert dca_run_log.item_evaluation("X", False, payload)["status"] == "job_failed"
    fresh = {**payload, "status": "running"}
    assert dca_run_log.item_evaluation("X", False, fresh) == {"status": "never_run", "reason": "running"}


def test_recording_failure_never_breaks_the_evaluation():
    class BrokenDb:
        info: dict = {}

        def add(self, row):
            raise RuntimeError("db down")

        def rollback(self):
            raise RuntimeError("db down")

    assert dca_run_log.start_run(BrokenDb(), "scheduler") is None
    dca_run_log.finish_run(BrokenDb(), None, summary={"tracked": 1})  # no-op, no excepcion


def test_actor_records_scheduler_run_and_error(monkeypatch):
    events: list[tuple] = []

    class FakeDb:
        def close(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr(dramatiq_app, "_session", lambda t, u: FakeDb())
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda name, **kw: "tok")
    monkeypatch.setattr(dramatiq_app, "release_job_lease", lambda *a, **kw: None)
    monkeypatch.setattr(dca_run_log, "start_run", lambda db, trigger: events.append(("start", trigger)) or "row")
    monkeypatch.setattr(
        dca_run_log, "finish_run",
        lambda db, row, summary=None, error=None: events.append(("finish", row, bool(error))),
    )
    monkeypatch.setattr("app.services.dca_signal_service.evaluate_watchlist", lambda db: {"evaluated": 1})
    dramatiq_app.evaluate_dca_signals.fn(7, "u-1")
    assert events == [("start", "scheduler"), ("finish", "row", False)]

    events.clear()

    def boom(db):
        raise ValueError("permanent")

    monkeypatch.setattr("app.services.dca_signal_service.evaluate_watchlist", boom)
    out = dramatiq_app.evaluate_dca_signals.fn(7, "u-1")
    assert out["status"] == "error"
    assert events == [("start", "scheduler"), ("finish", "row", True)]


def test_migration_0091_creates_adopts_and_rejects_drift(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0091_dca_evaluation_runs.py"
    spec = importlib.util.spec_from_file_location("dca_runs_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE tenants (id INTEGER PRIMARY KEY)")
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        assert inspect(conn).has_table("dca_evaluation_runs")
        module.upgrade()  # adopcion de un esquema identico
        module.downgrade()
        assert inspect(conn).has_table("dca_evaluation_runs")
        conn.exec_driver_sql("ALTER TABLE dca_evaluation_runs ADD COLUMN unexpected INTEGER")
        with pytest.raises(RuntimeError, match="schema mismatch"):
            module.upgrade()
