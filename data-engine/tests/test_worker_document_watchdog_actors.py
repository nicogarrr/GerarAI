"""process_document (slot de ingesta unica por proceso, fecha Z ISO,
errores con ticker) y los watchdogs de operador (lease, stats, rollback)."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.db_connection_watchdog as dbcw
import app.services.feed_ingestion_service as fis
import app.services.source_freshness_watchdog as sfw
import app.workers.ingest_slot as ingest_slot_mod
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
    monkeypatch.setattr(worker, "acquire_job_lease", lambda *a, **k: "L")
    released = []
    monkeypatch.setattr(worker, "release_job_lease",
                        lambda name, lease, **k: released.append(name))
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    return SimpleNamespace(db=db, released=released)


# --- process_document -----------------------------------------------------

def test_process_document_ok_con_slot_y_fecha_z(env, monkeypatch):
    held = []

    class FakeSlot:
        def hold(self):
            import contextlib

            return contextlib.nullcontext(held.append(1))

    seen = {}

    class FakeService:
        async def ingest_document_url(self, db_, **kw):
            seen.update(kw)
            return {"status": "ingested", "document_id": 5}

    monkeypatch.setattr(ingest_slot_mod, "document_ingest_slot", lambda: FakeSlot())
    monkeypatch.setattr(fis, "FeedIngestionService", FakeService)
    out = worker.process_document.fn(
        ticker="ACME", title="t", url="https://x", source_type="filing",
        published_at="2026-11-18T10:00:00Z", tenant_id=1, user_id="u")
    assert out["status"] == "ingested" and out["actor"] == "process_document"
    assert held == [1]  # el slot rodea toda la ingesta pesada
    assert seen["published_at"].tzinfo is not None  # la Z se parsea a tz-aware
    assert seen["ticker"] == "ACME"


def test_process_document_error_devuelve_ticker(env, monkeypatch):
    class FakeSlot:
        def hold(self):
            import contextlib

            return contextlib.nullcontext(None)

    class FakeService:
        async def ingest_document_url(self, db_, **kw):
            raise RuntimeError("docling caido")

    monkeypatch.setattr(ingest_slot_mod, "document_ingest_slot", lambda: FakeSlot())
    monkeypatch.setattr(fis, "FeedIngestionService", FakeService)
    out = worker.process_document.fn(ticker="ACME", title="t", url="https://x",
                                     source_type="filing", published_at=None)
    assert out["status"] == "error"
    assert out["error"]["context"]["ticker"] == "ACME"


# --- watchdogs --------------------------------------------------------------

def test_freshness_watchdog_ok_propaga_stats(env, monkeypatch):
    monkeypatch.setattr(sfw, "emit_source_freshness_alerts",
                        lambda db_: {"stale_sources": 2, "alerts_created": 2})
    out = worker.dispatch_source_freshness_watchdog.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["stale_sources"] == 2
    assert env.released == ["dispatch_source_freshness_watchdog:1"]


def test_freshness_watchdog_lease_ocupado_salta(env, monkeypatch):
    monkeypatch.setattr(worker, "acquire_job_lease", lambda *a, **k: None)
    out = worker.dispatch_source_freshness_watchdog.fn(tenant_id=1, user_id="u")
    assert out == {"status": "skipped",
                   "actor": "dispatch_source_freshness_watchdog",
                   "reason": "lease_held"}


def test_freshness_watchdog_error_hace_rollback(env, monkeypatch):
    monkeypatch.setattr(sfw, "emit_source_freshness_alerts",
                        lambda db_: (_ for _ in ()).throw(ValueError("sql")))
    rolled = []
    monkeypatch.setattr(env.db, "rollback", lambda: rolled.append(1))
    out = worker.dispatch_source_freshness_watchdog.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and rolled == [1]
    assert env.released == ["dispatch_source_freshness_watchdog:1"]


def test_db_watchdog_ok(env, monkeypatch):
    monkeypatch.setattr(dbcw, "emit_db_connection_alerts",
                        lambda db_: {"idle_in_tx": 1, "alerts_created": 1})
    out = worker.dispatch_db_connection_watchdog.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["idle_in_tx"] == 1
    assert env.released == ["dispatch_db_connection_watchdog:1"]


def test_db_watchdog_lease_ocupado(env, monkeypatch):
    monkeypatch.setattr(worker, "acquire_job_lease", lambda *a, **k: None)
    assert worker.dispatch_db_connection_watchdog.fn(tenant_id=1)["status"] == "skipped"


def test_db_watchdog_error_antes_de_sesion_sin_rollback(env, monkeypatch):
    monkeypatch.setattr(worker, "_session",
                        lambda t, u: (_ for _ in ()).throw(RuntimeError("pool")))
    out = worker.dispatch_db_connection_watchdog.fn(tenant_id=1)
    assert out["status"] == "error" and out["actor"] == "dispatch_db_connection_watchdog"
