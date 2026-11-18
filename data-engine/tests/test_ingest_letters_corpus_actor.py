"""ingest_letters_corpus: cuerpo del actor sin test directo.

Los tests de la ruta (test_knowledge_corpus_ingest_async, test_thin_routes_batch12)
sustituyen el actor por un falso; su cuerpo no lo ejecutaba ninguno.

Contratos fijados:
- exito: devuelve ``actor`` + resultado del servicio, libera el lease y cierra la sesion;
- lease ocupado: skipped/lease_held, sin llamar al servicio, sesion cerrada y sin liberar;
- fallo del servicio: el lease se libera SIEMPRE, la sesion se cierra y el error sale
  estructurado por _handle_actor_error;
- fallo al adquirir el lease: sesion cerrada y error estructurado;
- fallo de _session: error estructurado (no revienta crudo).

Run from data-engine/:
    pytest tests/test_ingest_letters_corpus_actor.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import corpus_ingestion_service
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    e = SimpleNamespace(
        db=MagicMock(), lease="LEASE", acquired=[], released=[], handled=[],
        session_error=None, acquire_error=None,
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
    monkeypatch.setattr(worker, "_handle_actor_error", handle)
    monkeypatch.setattr(worker, "_redis_client", lambda: None)  # coalescencia fail-open
    return e


def test_ok_devuelve_resultado_libera_lease_y_cierra(env, monkeypatch):
    seen = {}

    def ingest(db):
        seen["db"] = db
        return {"status": "ok", "ingested": 4}

    monkeypatch.setattr(corpus_ingestion_service, "ingest_free_corpus", ingest)

    out = worker.ingest_letters_corpus.fn(tenant_id=3, user_id="u")

    assert out == {"actor": "ingest_letters_corpus", "status": "ok", "ingested": 4}
    assert seen["db"] is env.db
    assert env.acquired == [("ingest_letters_corpus:3", 3600)]
    assert env.released == [("ingest_letters_corpus:3", "LEASE")]
    env.db.close.assert_called_once_with()


def test_lease_ocupado_no_trabaja_ni_libera(env, monkeypatch):
    env.lease = None
    called = []
    monkeypatch.setattr(corpus_ingestion_service, "ingest_free_corpus", lambda db: called.append(db))

    out = worker.ingest_letters_corpus.fn(tenant_id=3, user_id="u")

    assert out == {"status": "skipped", "actor": "ingest_letters_corpus", "reason": "lease_held"}
    assert called == []
    assert env.released == []
    env.db.close.assert_called_once_with()


def test_fallo_del_servicio_libera_lease_cierra_y_estructura(env, monkeypatch):
    boom = KeyError("fuente")

    def fail(db):
        raise boom

    monkeypatch.setattr(corpus_ingestion_service, "ingest_free_corpus", fail)

    out = worker.ingest_letters_corpus.fn(tenant_id=3, user_id="u")

    assert out["status"] == "error"
    assert env.handled[0][1] is boom
    assert env.handled[0][2] == {"tenant_id": 3}
    assert env.released == [("ingest_letters_corpus:3", "LEASE")]
    env.db.close.assert_called_once_with()


def test_fallo_al_adquirir_lease_cierra_sesion_y_estructura(env, monkeypatch):
    env.acquire_error = ConnectionError("redis")
    called = []
    monkeypatch.setattr(corpus_ingestion_service, "ingest_free_corpus", lambda db: called.append(db))

    out = worker.ingest_letters_corpus.fn(tenant_id=3, user_id="u")

    assert out["status"] == "error"
    assert isinstance(env.handled[0][1], ConnectionError)
    assert called == []
    assert env.released == []
    env.db.close.assert_called_once_with()


def test_error_de_sesion_no_revienta_crudo(env, monkeypatch):
    env.session_error = ValueError("tenant inactivo")

    out = worker.ingest_letters_corpus.fn(tenant_id=3, user_id="u")

    assert out["status"] == "error"
    assert isinstance(env.handled[0][1], ValueError)
    assert env.acquired == []
