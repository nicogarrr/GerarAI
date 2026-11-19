"""dispatch_macro_reminders con sesion SQLite real: lease, fuente de
calendario no disponible (skip sin inventar recordatorios), emision +
re-dispatch pendientes, y lease liberado en todos los caminos."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.macro_calendar_service as mcs
import app.services.macro_reminders as mr
import app.services.outbound_alerts as oa
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
    e = SimpleNamespace(db=db, released=[], calendar={"status": "ok", "events": []},
                        emit_stats={"created": 2, "existing": 1},
                        pending={"redispatched": 3, "errors": []})
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    monkeypatch.setattr(worker, "acquire_job_lease", lambda key, **kw: "LEASE")
    monkeypatch.setattr(worker, "release_job_lease",
                        lambda key, lease, **kw: e.released.append((key, lease)))

    async def fake_calendar(start, end):
        return e.calendar

    monkeypatch.setattr(mcs, "get_macro_events", fake_calendar)
    monkeypatch.setattr(mr, "emit_macro_reminders", lambda db_, events: e.emit_stats)
    monkeypatch.setattr(oa, "dispatch_pending", lambda db_: e.pending)
    return e


def test_flujo_ok_emite_y_redespacha(env):
    out = worker.dispatch_macro_reminders.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok"
    assert (out["created"], out["existing"], out["redispatched"]) == (2, 1, 3)
    assert env.released == [("dispatch_macro_reminders:1", "LEASE")]


def test_lease_en_curso_skips(env, monkeypatch):
    monkeypatch.setattr(worker, "acquire_job_lease", lambda key, **kw: None)
    out = worker.dispatch_macro_reminders.fn(tenant_id=1, user_id="u")
    assert out["reason"] == "lease_held" and env.released == []


def test_fuente_no_disponible_skips_sin_inventar(env):
    env.calendar = {"status": "unavailable"}
    out = worker.dispatch_macro_reminders.fn(tenant_id=1, user_id="u")
    assert out["reason"] == "source_unavailable"
    assert env.released  # lease liberado tambien en skip


def test_error_rollback_y_lease_liberado(env, monkeypatch):
    # dispatch_pending es la ultima llamada: su fallo ejercita el except.
    monkeypatch.setattr(oa, "dispatch_pending",
                        lambda db_: (_ for _ in ()).throw(RuntimeError("pg caido")))
    out = worker.dispatch_macro_reminders.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["actor"] == "dispatch_macro_reminders"
    assert env.released


def test_error_de_sesion_sin_rollback(env, monkeypatch):
    # db nunca llega a existir: el except no debe hacer rollback.
    monkeypatch.setattr(worker, "_session",
                        lambda t, u: (_ for _ in ()).throw(ValueError("sin db")))
    out = worker.dispatch_macro_reminders.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["actor"] == "dispatch_macro_reminders"
