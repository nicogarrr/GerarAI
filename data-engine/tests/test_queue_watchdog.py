"""Pruebas del watchdog de colas atascadas (alerta in-app al operador).

Fulfills: VAL-PERF-queues (petición de Nico del 1-nov-2026: el lunes entra la
carga de noticias y precios y una cola atascada debe alertar por lo medido).
Expected Behavior:
- La muestra mide profundidad (msgs + DQ.msgs) y la edad de la CABEZA de la
  lista ready por persistencia del ready id (nunca message_timestamp: incluye
  el cooldown de RetryAfter y alertaría en un reintento normal)
- Atasco = cabeza >= umbral Y variación neta de profundidad <= 0 entre ticks;
  decreciendo o joven no alerta; el primer tick solo guarda la muestra
- Una medición por tick aunque el actor corra por tenant: el primero muestrea
  (lease global), los demás reutilizan el resultado y NO pisan la muestra
- ResearchAlert in-app idempotente por tenant, cola y día con lo medido;
  Redis caído o lectura fallida = fail-open (skipped)
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import ResearchAlert, Tenant
from app.models.entities import Base
from app.services import queue_watchdog as wd

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)


def make_db(tenant: int):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Tenant(id=tenant, external_id=f"owner{tenant}"))
    session.commit()
    session.info.update(tenant_id=tenant, user_id=f"owner{tenant}")
    return session


@pytest.fixture
def db():
    session = make_db(1)
    yield session
    session.close()


@pytest.fixture
def redis_client():
    fakeredis = pytest.importorskip("fakeredis")
    return fakeredis.FakeRedis(decode_responses=False)


def _push(client, queue: str, *, age_seconds: float = 0, namespace: str = "dramatiq") -> str:
    """Encola un mensaje dramatiq 1.x sintético; message_timestamp viejo simula
    uno que esperó un RetryAfter en la cola diferida antes de estar listo."""
    import dramatiq

    decoded = json.loads(
        dramatiq.Message(queue_name=queue, actor_name="actor_test", args=(), kwargs={}, options={}).encode()
    )
    decoded["message_timestamp"] = int(NOW.timestamp() * 1000 - age_seconds * 1000)
    mid = decoded["message_id"]
    base = f"{namespace}:{queue}"
    client.hset(f"{base}.msgs", mid, json.dumps(decoded))
    client.rpush(base, mid)
    return mid


def _next_tick(client, at: datetime):
    """Simula el siguiente tick del scheduler: expira el lease y el resultado."""
    client.delete(wd._TICK_LOCK_KEY)
    client.delete(wd._RESULT_KEY)
    return at


# --- Punto 3 de la auditoría: edad por persistencia del ready id -------------

def test_edad_por_persistencia_no_message_timestamp(redis_client):
    # Mensaje con message_timestamp de hace 1 h (esperó un RetryAfter): al
    # aparecer en cabeza por primera vez su edad lista es 0, no 3600 s.
    _push(redis_client, "prices", age_seconds=3600)
    (sample,) = wd.sample_queues(redis_client, queues=("prices",), now_ms=NOW.timestamp() * 1000)
    assert sample.depth == 1
    assert sample.ready_age_seconds == 0.0
    # Mismo id en cabeza 400 s después: la edad crece desde que se vio listo.
    later = NOW.timestamp() * 1000 + 400_000
    (sample,) = wd.sample_queues(redis_client, queues=("prices",), now_ms=later)
    assert 395 <= sample.ready_age_seconds <= 405


def test_cabeza_nueva_reinicia_edad_y_cola_vacia_la_borra(redis_client):
    _push(redis_client, "prices")
    wd.sample_queues(redis_client, queues=("prices",), now_ms=NOW.timestamp() * 1000)
    _push(redis_client, "prices")  # nueva cabeza (LIFO no: RPUSH -> la vieja sigue en cabeza)
    (sample,) = wd.sample_queues(redis_client, queues=("prices",), now_ms=NOW.timestamp() * 1000 + 60_000)
    assert sample.ready_age_seconds == 60.0  # la cabeza original sigue
    # Consumir ambas: cola vacía -> edad None y anotación borrada.
    redis_client.lrange("dramatiq:prices", 0, -1) and [
        redis_client.lrem("dramatiq:prices", 1, mid) for mid in redis_client.lrange("dramatiq:prices", 0, -1)
    ]
    (sample,) = wd.sample_queues(redis_client, queues=("prices",), now_ms=NOW.timestamp() * 1000 + 120_000)
    assert sample.ready_age_seconds is None
    assert redis_client.get(f"{wd._HEAD_PREFIX}prices") is None


# --- Detección pura: variación neta de profundidad, no completados ------------

def test_detect_stuck_alerta_cabeza_vieja_sin_decrecer():
    now = time.time()
    prev = {"prices": {"ts": now - 300, "depth": 10.0}}
    # Entran 2 y salen 0: crece. Variación neta negativa.
    samples = [wd.QueueSample(queue="prices", depth=12, ready_age_seconds=1000.0)]
    (stuck,) = wd.detect_stuck(samples, prev, max_age=900.0, now=now)
    assert stuck["queue"] == "prices"
    assert stuck["net_rate_per_s"] < 0


def test_detect_stuck_entran_y_salen_50_es_atasco_si_cabeza_vieja():
    # 50 completados y 50 nuevos: variación neta 0 -> sigue atascada (la cabeza
    # no avanza). "Drenar" por throughput no basta: lo que importa es que la
    # profundidad decrezca.
    now = time.time()
    prev = {"prices": {"ts": now - 300, "depth": 10.0}}
    samples = [wd.QueueSample(queue="prices", depth=10, ready_age_seconds=1000.0)]
    assert len(wd.detect_stuck(samples, prev, max_age=900.0, now=now)) == 1


def test_detect_stuck_no_alerta_si_decrece_joven_o_sin_previa():
    now = time.time()
    prev = {"prices": {"ts": now - 300, "depth": 20.0}}
    decrece = [wd.QueueSample(queue="prices", depth=10, ready_age_seconds=1000.0)]
    assert wd.detect_stuck(decrece, prev, max_age=900.0, now=now) == []
    joven = [wd.QueueSample(queue="prices", depth=50, ready_age_seconds=10.0)]
    assert wd.detect_stuck(joven, prev, max_age=900.0, now=now) == []
    viejo = [wd.QueueSample(queue="prices", depth=50, ready_age_seconds=5000.0)]
    assert wd.detect_stuck(viejo, {"prices": None}, max_age=900.0, now=now) == []


# --- Punto 1: una medición por tick aunque el actor corra por tenant ---------

def test_una_medicion_por_tick_los_demas_tenants_reusan(db, redis_client):
    t0 = NOW - timedelta(seconds=1000)
    # Tick anterior: siembra muestra y cabeza (edad 0 entonces).
    stats = wd.emit_queue_stuck_alerts(db, client=redis_client, now=t0)
    assert stats["sampled"] is True
    assert stats["created"] == []
    _push(redis_client, "prices")  # mensaje que quedará en cabeza 1000 s
    wd.sample_tick(redis_client, namespace="dramatiq", queues=("prices",), now=t0 + timedelta(seconds=1))
    # Tick actual, tenant 1 (muestreador): detecta atasco (cabeza 999 s, depth 1->1).
    _next_tick(redis_client, NOW)
    stats1 = wd.emit_queue_stuck_alerts(db, client=redis_client, now=NOW)
    assert stats1["sampled"] is True
    assert len(stats1["created"]) == 1
    sample_after_t1 = wd.load_previous(redis_client, "prices")
    # Tenant 2, milisegundos después: reutiliza el resultado y NO pisa la muestra.
    db2 = make_db(2)
    try:
        stats2 = wd.emit_queue_stuck_alerts(
            db2, client=redis_client, now=NOW + timedelta(milliseconds=50)
        )
        assert stats2["sampled"] is False
        assert len(stats2["created"]) == 1  # su propia alerta por tenant
        assert wd.load_previous(redis_client, "prices") == sample_after_t1
    finally:
        db2.close()


def test_tenant_sin_resultado_cacheado_difiere_sin_alerta_falsa(db, redis_client):
    # Lease tomado por otro tenant pero resultado aún no publicado: se salta.
    redis_client.set(wd._TICK_LOCK_KEY, "1", ex=240)
    stats = wd.emit_queue_stuck_alerts(db, client=redis_client, now=NOW)
    assert stats["sampled"] is False
    assert stats["deferred"] is True
    assert stats["created"] == []


# --- Alerta idempotente con lo medido -----------------------------------------

def test_emit_crea_alerta_idempotente_con_lo_medido(db, redis_client):
    _push(redis_client, "prices")
    # Tick previo (siembra): cabeza vista por primera vez hace 1000 s.
    wd.sample_tick(redis_client, namespace="dramatiq", queues=("prices",),
                   now=NOW - timedelta(seconds=1000))
    stats = wd.emit_queue_stuck_alerts(db, client=redis_client, now=NOW)
    assert stats["stuck"] == 1
    assert len(stats["created"]) == 1
    alert = db.scalars(select(ResearchAlert)).one()
    assert alert.alert_type == "queue_stuck"
    assert alert.channels == ["in_app"]
    assert "999" in alert.message or "1000" in alert.message  # edad de cabeza
    assert "variacion neta" in alert.message
    # Segundo tick el mismo día (sigue atascada): deduplica por fingerprint.
    _next_tick(redis_client, NOW + timedelta(seconds=300))
    stats2 = wd.emit_queue_stuck_alerts(db, client=redis_client, now=NOW + timedelta(seconds=300))
    assert stats2["created"] == []
    assert stats2["existing"] == 1
    assert len(db.scalars(select(ResearchAlert)).all()) == 1


def test_primer_tick_solo_guarda_muestra(db, redis_client):
    _push(redis_client, "prices")
    stats = wd.emit_queue_stuck_alerts(db, client=redis_client, now=NOW)
    assert stats["status"] == "ok"
    assert stats["created"] == []
    assert wd.load_previous(redis_client, "prices") == {"ts": NOW.timestamp(), "depth": 1.0}
    assert db.scalars(select(ResearchAlert)).all() == []


# --- Punto 4: lista de colas completa ------------------------------------------

def test_default_queues_cubre_todas_las_declaradas():
    import app.workers.dramatiq_app as dapp
    import app.workers.knowledge_rag_actors as rag

    declared = {
        dapp.KPI_QUEUE_NAME, dapp.ALERT_QUEUE_NAME, dapp.GDELT_QUEUE_NAME,
        dapp.COMPUTED_QUEUE_NAME, dapp.EXTERNA_QUEUE_NAME, dapp.FINNHUB_QUEUE_NAME,
        dapp.YAHOO_QUEUE_NAME, rag.KNOWLEDGE_QUEUE_NAME, "default", "prices", "thesis",
    }
    assert declared <= set(wd.DEFAULT_QUEUES)


# --- Punto 5: Redis caído o lectura fallida = fail-open ------------------------

def test_emit_sin_redis_fail_open(db, monkeypatch):
    import app.workers.dramatiq_app as dapp

    monkeypatch.setattr(dapp, "_redis_client", lambda: None)
    stats = wd.emit_queue_stuck_alerts(db, now=NOW)
    assert stats["status"] == "skipped"
    assert stats["reason"] == "redis_unavailable"


def test_emit_con_redis_roto_fail_open(db):
    import redis.exceptions

    class BrokenRedis:
        def set(self, *a, **k):
            raise redis.exceptions.ConnectionError("caido")

    stats = wd.emit_queue_stuck_alerts(db, client=BrokenRedis(), now=NOW)
    assert stats["status"] == "skipped"
    assert stats["reason"] == "redis_unavailable"
    assert stats["created"] == []
