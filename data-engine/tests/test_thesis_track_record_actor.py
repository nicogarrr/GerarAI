"""Actores sin cobertura directa: refresh_thesis_track_record e ingest_knowledge_source.

El cuerpo de ``refresh_thesis_track_record`` (app/workers/thesis_track_record_actors.py)
no lo ejecutaba ningun test: la cobertura medida del modulo era 38.1 % (13 de 21
sentencias sin cubrir, lineas 24-38) y el actor solo se ejercitaba en produccion.
``ingest_knowledge_source`` (app/workers/knowledge_rag_actors.py) estaba en la misma
situacion: los tests vecinos solo stubban ``.send`` o verifican opciones.

Contratos fijados aqui (mismo patron que test_worker_uncovered_actors.py):
- exito: la sesion se cierra SIEMPRE y el resultado lleva actor/tenant_id;
- fallo del servicio: rollback + payload estructurado de _handle_actor_error,
  la excepcion no se propaga cruda;
- fallo de _session en refresh: pasa por _handle_actor_error (un ValueError
  permanente de sesion no debe reventar crudo: dramatiq lo reintentaria y lo
  mandaria a dead-letter sin registro estructurado);
- la coalescencia del refresh (claim denegado) skippea sin crear sesion ni
  llamar al servicio;
- registro: colas, reintentos y politica de coalescencia declarados.

Run from data-engine/:
    pytest tests/test_thesis_track_record_actor.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.services.thesis_track_record_service as track_record_service
from app.services.knowledge_rag import jobs as knowledge_jobs
from app.workers import dramatiq_app as worker
from app.workers import knowledge_rag_actors as krag_actors
from app.workers import thesis_track_record_actors as ttr_actors


@pytest.fixture()
def env(monkeypatch):
    """Sesion/handle falsos y coalescencia fail-open; nada toca Redis ni Postgres."""
    e = SimpleNamespace(
        db=MagicMock(),
        handled=[],
        session_error=None,
        service_error=None,
        service_result=None,
        service_calls=[],
    )

    def session(tenant, user):
        if e.session_error:
            raise e.session_error
        return e.db

    def handle(actor, exc, **ctx):
        e.handled.append((actor, exc, ctx))
        return {"status": "error", "actor": actor, "error": {"type": type(exc).__name__}}

    # Coalescencia fail-open sin Redis (misma fijacion que test_worker_uncovered_actors).
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    monkeypatch.setattr(ttr_actors, "_session", session)
    monkeypatch.setattr(ttr_actors, "_handle_actor_error", handle)
    monkeypatch.setattr(krag_actors, "_session", session)
    monkeypatch.setattr(krag_actors, "_handle_actor_error", handle)
    return e


# --- refresh_thesis_track_record -------------------------------------------


def test_refresh_track_record_ok_cierra_sesion_y_devuelve_actor(env, monkeypatch):
    def refresh(db):
        env.service_calls.append(db)
        return {"status": "ok", "refreshed": 3}

    monkeypatch.setattr(track_record_service, "refresh_track_record", refresh)

    out = ttr_actors.refresh_thesis_track_record.fn(tenant_id=7, user_id="u")

    assert out == {"status": "ok", "refreshed": 3, "actor": "refresh_thesis_track_record", "tenant_id": 7}
    assert env.service_calls == [env.db]
    env.db.close.assert_called_once_with()


def test_refresh_track_record_error_hace_rollback_y_handle_estructurado(env, monkeypatch):
    boom = KeyError("qdrant")

    def fail(db):
        raise boom

    monkeypatch.setattr(track_record_service, "refresh_track_record", fail)

    out = ttr_actors.refresh_thesis_track_record.fn(tenant_id=7, user_id="u")

    assert out["status"] == "error"
    assert env.handled and env.handled[0][0] == "refresh_thesis_track_record"
    assert env.handled[0][1] is boom
    env.db.rollback.assert_called_once_with()
    env.db.close.assert_called_once_with()


def test_refresh_track_record_error_de_sesion_no_revienta_crudo(env, monkeypatch):
    env.session_error = ValueError("tenant inactivo")
    called = []
    monkeypatch.setattr(track_record_service, "refresh_track_record", lambda db: called.append(db))

    out = ttr_actors.refresh_thesis_track_record.fn(tenant_id=7, user_id="u")

    assert out["status"] == "error"
    assert env.handled[0][0] == "refresh_thesis_track_record"
    assert isinstance(env.handled[0][1], ValueError)
    assert called == []  # nunca llego al servicio


def test_refresh_track_record_coalesce_skippea_sin_trabajar(env, monkeypatch):
    """Un claim fresco (otra copia en vuelo) devuelve skipped sin sesion ni servicio."""

    class _DenyClaim:
        def delete(self, *a):
            pass

        def set(self, *a, **kw):
            return None  # SET NX no concedido: ya hay una copia fresca

    monkeypatch.setattr(worker, "_redis_client", lambda: _DenyClaim())
    called = []
    monkeypatch.setattr(track_record_service, "refresh_track_record", lambda db: called.append(db))

    out = ttr_actors.refresh_thesis_track_record.fn(tenant_id=7, user_id="u")

    assert out == {
        "status": "skipped",
        "actor": "refresh_thesis_track_record",
        "reason": "fresh_or_running",
        "window_seconds": 20 * 3600,
    }
    assert called == []


def test_refresh_track_record_registro_y_coalescencia_declarados():
    actor = ttr_actors.refresh_thesis_track_record
    assert actor.actor_name == "refresh_thesis_track_record"
    assert actor.options["max_retries"] == 1
    policy = worker._COALESCE_POLICIES["refresh_thesis_track_record"]
    assert policy["window"] == 20 * 3600
    assert policy["key_parts"] == ("tenant_id",)


# --- ingest_knowledge_source ------------------------------------------------


def test_ingest_knowledge_source_ok_cierra_sesion(env, monkeypatch):
    def run(db, source_id, settings):
        env.service_calls.append((db, source_id))
        return {"status": "ok", "source_id": source_id, "chunks": 12}

    monkeypatch.setattr(knowledge_jobs, "run_ingest_job", run)

    out = krag_actors.ingest_knowledge_source.fn(55, tenant_id=7, user_id="u")

    assert out == {"status": "ok", "source_id": 55, "chunks": 12}
    assert env.service_calls == [(env.db, 55)]
    env.db.close.assert_called_once_with()


def test_ingest_knowledge_source_error_handle_estructurado_con_source_id(env, monkeypatch):
    boom = RuntimeError("docling OOM")

    def fail(db, source_id, settings):
        raise boom

    monkeypatch.setattr(knowledge_jobs, "run_ingest_job", fail)

    out = krag_actors.ingest_knowledge_source.fn(55, tenant_id=7, user_id="u")

    assert out["status"] == "error"
    assert env.handled and env.handled[0][0] == "ingest_knowledge_source"
    assert env.handled[0][1] is boom
    assert env.handled[0][2] == {"source_id": 55}  # trazabilidad de la fuente fallida
    env.db.close.assert_called_once_with()


def test_ingest_knowledge_source_error_de_sesion_no_revienta_crudo(env, monkeypatch):
    """Un ValueError permanente de _session pasa por _handle_actor_error.

    Antes iba por fuera del try: dramatiq lo reintentaba dos veces y lo
    mandaba a dead-letter sin registro estructurado (mismo contrato que
    test_worker_uncovered_actors fijo para ingest_class_shares_outstanding).
    """
    env.session_error = ValueError("tenant inactivo")
    called = []
    monkeypatch.setattr(knowledge_jobs, "run_ingest_job", lambda db, sid, st: called.append(sid))

    out = krag_actors.ingest_knowledge_source.fn(55, tenant_id=7, user_id="u")

    assert out["status"] == "error"
    assert env.handled[0][0] == "ingest_knowledge_source"
    assert isinstance(env.handled[0][1], ValueError)
    assert env.handled[0][2] == {"source_id": 55}
    assert called == []


def test_ingest_knowledge_source_registro_en_cola_dedicada():
    actor = krag_actors.ingest_knowledge_source
    assert actor.queue_name == krag_actors.KNOWLEDGE_QUEUE_NAME == "knowledge"
    assert actor.options["max_retries"] == 2
    assert actor.options["min_backoff"] == 60_000
