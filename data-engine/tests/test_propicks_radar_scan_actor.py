"""propicks_radar_scan: cuerpo del actor sin test directo.

Los tests vecinos (test_radar_scan_enqueued_once, test_propicks_radar_route) solo
comprueban el encolado y el error de sesion; el cuerpo no lo ejecutaba ninguno.

Contratos fijados:
- exito: ``actor`` + resultado del barrido, lease global liberado y sesion cerrada;
- lease ocupado: skipped/lease_held, el barrido no corre, no se libera lo ajeno;
- fallo del barrido: rollback, lease liberado SIEMPRE, sesion cerrada, error estructurado;
- fallo al adquirir el lease: la excepcion se propaga (reintento de dramatiq) y la
  sesion se cierra;
- el lease es global (clave sin tenant: datos publicos) y de 1 h.

Run from data-engine/:
    pytest tests/test_propicks_radar_scan_actor.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import propicks_radar_job
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    e = SimpleNamespace(
        db=MagicMock(), lease="LEASE", acquired=[], released=[], handled=[], rolled=[],
        acquire_error=None,
    )

    def acquire(key, **kw):
        if e.acquire_error:
            raise e.acquire_error
        e.acquired.append((key, kw["ttl_seconds"]))
        return e.lease

    def handle(actor, exc, **ctx):
        e.handled.append((actor, exc, ctx))
        return {"status": "error", "actor": actor, "error": {"type": type(exc).__name__}}

    monkeypatch.setattr(worker, "_session", lambda tenant, user: e.db)
    monkeypatch.setattr(worker, "acquire_job_lease", acquire)
    monkeypatch.setattr(worker, "release_job_lease", lambda key, lease, **kw: e.released.append((key, lease)))
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    monkeypatch.setattr(worker, "_rollback", lambda db: e.rolled.append(db))
    monkeypatch.setattr(worker, "_handle_actor_error", handle)
    return e


def test_ok_devuelve_resultado_libera_lease_global_y_cierra(env, monkeypatch):
    seen = {}

    def scan(db):
        seen["db"] = db
        return {"status": "ok", "scanned": 12}

    monkeypatch.setattr(propicks_radar_job, "run_radar_scan", scan)

    out = worker.propicks_radar_scan.fn(tenant_id=5, user_id="u")

    assert out == {"actor": "propicks_radar_scan", "status": "ok", "scanned": 12}
    assert seen["db"] is env.db
    assert env.acquired == [("propicks_radar_scan", 3600)]  # global, sin tenant
    assert env.released == [("propicks_radar_scan", "LEASE")]
    env.db.close.assert_called_once_with()


def test_lease_ocupado_no_barre_ni_libera(env, monkeypatch):
    env.lease = None
    called = []
    monkeypatch.setattr(propicks_radar_job, "run_radar_scan", lambda db: called.append(db))

    out = worker.propicks_radar_scan.fn(tenant_id=5, user_id="u")

    assert out == {"status": "skipped", "actor": "propicks_radar_scan", "reason": "lease_held"}
    assert called == []
    assert env.released == []
    env.db.close.assert_called_once_with()


def test_fallo_del_barrido_rollback_libera_lease_y_estructura(env, monkeypatch):
    boom = KeyError("snapshot")

    def fail(db):
        raise boom

    monkeypatch.setattr(propicks_radar_job, "run_radar_scan", fail)

    out = worker.propicks_radar_scan.fn(tenant_id=5, user_id="u")

    assert out["status"] == "error"
    assert env.handled[0][1] is boom
    assert env.handled[0][2] == {"tenant_id": 5}
    assert env.rolled == [env.db]
    assert env.released == [("propicks_radar_scan", "LEASE")]
    env.db.close.assert_called_once_with()


def test_fallo_al_adquirir_lease_propaga_y_cierra_sesion(env, monkeypatch):
    env.acquire_error = ConnectionError("redis")
    called = []
    monkeypatch.setattr(propicks_radar_job, "run_radar_scan", lambda db: called.append(db))

    with pytest.raises(ConnectionError):
        worker.propicks_radar_scan.fn(tenant_id=5, user_id="u")

    assert called == []
    assert env.released == []
    env.db.close.assert_called_once_with()
