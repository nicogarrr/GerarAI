"""ingest_house_ptr: los PDF que fallan tambien gastan el presupuesto max_new.

ingest_year descuenta un PDF por cada PTR electronico intentado, falle o no.
El actor solo restaba (new - scanned), asi que con PDFs fallidos pedia al año
anterior mas presupuesto del que quedaba y superaba el tope total.
"""
from __future__ import annotations
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from app.services import politician_trades
from app.workers import dramatiq_app as worker



@pytest.fixture()
def env(monkeypatch):
    e = SimpleNamespace(db=MagicMock(), lease="LEASE", released=[], acquired=[], rolled=[],
                        session_error=None, handled=[], calls=[])

    def session(tenant, user):
        if e.session_error:
            raise e.session_error
        return e.db

    def acquire(key, **kw):
        e.acquired.append((key, kw["ttl_seconds"]))
        return e.lease

    def handle(actor, exc, **ctx):
        e.handled.append((actor, exc, ctx))
        return {"status": "error", "actor": actor, "error": {"type": type(exc).__name__}}

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 17, 12, 0, tzinfo=UTC)

    monkeypatch.setattr(worker, "_session", session)
    monkeypatch.setattr(worker, "acquire_job_lease", acquire)
    monkeypatch.setattr(worker, "release_job_lease", lambda key, lease, **kw: e.released.append((key, lease)))
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    monkeypatch.setattr(worker, "_rollback", lambda db: e.rolled.append(db))
    monkeypatch.setattr(worker, "_handle_actor_error", handle)
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    monkeypatch.setattr(worker, "datetime", _Clock)
    return e


def _ingest_year(env, results):
    def fake(db, year, *, tenant_id=None, max_new=120, **kw):
        env.calls.append({"year": year, "tenant_id": tenant_id, "max_new": max_new})
        return results[year]
    return fake



def test_house_ptr_pdfs_fallidos_gastan_presupuesto(env, monkeypatch):
    # 2026: 3 PDF intentados, 1 ok y 2 fallidos -> gastados 3 -> quedan 7.
    monkeypatch.setattr(politician_trades, "ingest_year", _ingest_year(env, {
        2026: {"year": 2026, "new": 1, "scanned": 0, "errors": ["a: X", "b: X"]},
        2025: {"year": 2025, "new": 0, "scanned": 0, "errors": []},
    }))
    worker.ingest_house_ptr.fn(tenant_id=3, user_id="u", max_new=10)
    assert [c["max_new"] for c in env.calls] == [10, 7]


def test_house_ptr_todo_fallido_agota_presupuesto_y_no_pide_el_ano_anterior(env, monkeypatch):
    monkeypatch.setattr(politician_trades, "ingest_year", _ingest_year(env, {
        2026: {"year": 2026, "new": 0, "scanned": 0, "errors": ["a: X", "b: X"]},
    }))
    worker.ingest_house_ptr.fn(tenant_id=3, user_id="u", max_new=2)
    assert [c["year"] for c in env.calls] == [2026]
