"""Pruebas del watchdog de colas atascadas (alerta in-app al operador).

Fulfills: VAL-PERF-queues (petición de Nico del 1-nov-2026: el lunes entra la
carga de noticias y precios y una cola atascada debe alertar por lo medido).
Expected Behavior:
- La muestra mide profundidad (msgs + DQ.msgs) y edad del mensaje listo más
  antiguo del formato dramatiq 1.x sobre Redis; una cola vacía no tiene edad
- Atasco = edad >= umbral Y tasa de drenaje <= 0 entre dos ticks; drenando o
  joven no alerta; el primer tick solo guarda la muestra
- La alerta es una ResearchAlert in-app idempotente por cola y día, con los
  números medidos en el mensaje; Redis caído = fail-open (skipped)
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import ResearchAlert, Tenant
from app.models.entities import Base
from app.services import queue_watchdog as wd

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="owner"))
        session.commit()
        session.info.update(tenant_id=1, user_id="owner")
        yield session
    engine.dispose()


@pytest.fixture
def redis_client():
    fakeredis = pytest.importorskip("fakeredis")
    return fakeredis.FakeRedis(decode_responses=False)


def _push(client, queue: str, *, age_seconds: float, namespace: str = "dramatiq") -> str:
    """Encola un mensaje dramatiq 1.x sintético con edad controlada."""
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


def test_sample_mide_profundidad_y_edad(redis_client):
    _push(redis_client, "prices", age_seconds=300)
    _push(redis_client, "prices", age_seconds=120)
    (sample,) = wd.sample_queues(redis_client, queues=("prices",), now_ms=NOW.timestamp() * 1000)
    assert sample.queue == "prices"
    assert sample.depth == 2
    assert 295 <= sample.oldest_age_seconds <= 305


def test_sample_cola_vacia_no_tiene_edad(redis_client):
    (sample,) = wd.sample_queues(redis_client, queues=("alerts",), now_ms=NOW.timestamp() * 1000)
    assert sample.depth == 0
    assert sample.oldest_age_seconds is None


def test_detect_stuck_alerta_viejo_sin_drenaje():
    now = time.time()
    prev = {"prices": {"ts": now - 300, "depth": 10.0}}
    samples = [wd.QueueSample(queue="prices", depth=12, oldest_age_seconds=1000.0)]
    (stuck,) = wd.detect_stuck(samples, prev, max_age=900.0, now=now)
    assert stuck["queue"] == "prices"
    assert stuck["depth"] == 12
    assert stuck["drain_rate_per_s"] < 0  # crece: tasa negativa


def test_detect_stuck_no_alerta_si_drena():
    now = time.time()
    prev = {"prices": {"ts": now - 300, "depth": 20.0}}
    samples = [wd.QueueSample(queue="prices", depth=10, oldest_age_seconds=1000.0)]
    assert wd.detect_stuck(samples, prev, max_age=900.0, now=now) == []


def test_detect_stuck_no_alerta_si_joven_o_sin_previa():
    now = time.time()
    prev = {"prices": {"ts": now - 300, "depth": 10.0}}
    joven = [wd.QueueSample(queue="prices", depth=50, oldest_age_seconds=10.0)]
    assert wd.detect_stuck(joven, prev, max_age=900.0, now=now) == []
    viejo = [wd.QueueSample(queue="prices", depth=50, oldest_age_seconds=5000.0)]
    assert wd.detect_stuck(viejo, {"prices": None}, max_age=900.0, now=now) == []


def test_primer_tick_solo_guarda_muestra(db, redis_client):
    _push(redis_client, "prices", age_seconds=5000)
    stats = wd.emit_queue_stuck_alerts(db, client=redis_client, now=NOW)
    assert stats["status"] == "ok"
    assert stats["created"] == []
    prev = wd.load_previous(redis_client, "prices")
    assert prev == {"ts": NOW.timestamp(), "depth": 1.0}
    assert db.scalars(select(ResearchAlert)).all() == []


def test_emit_crea_alerta_idempotente_con_lo_medido(db, redis_client):
    _push(redis_client, "prices", age_seconds=3600)
    wd.save_sample(redis_client, "prices", ts=NOW.timestamp() - 300, depth=1)
    stats = wd.emit_queue_stuck_alerts(db, client=redis_client, now=NOW)
    assert stats["stuck"] == 1
    assert len(stats["created"]) == 1
    alert = db.scalars(select(ResearchAlert)).one()
    assert alert.alert_type == "queue_stuck"
    assert alert.channels == ["in_app"]
    assert "3600" in alert.message or "3599" in alert.message
    assert "1 mensajes" in alert.message
    # Segundo tick el mismo día (sigue atascada): deduplica por fingerprint.
    stats2 = wd.emit_queue_stuck_alerts(db, client=redis_client, now=NOW)
    assert stats2["created"] == []
    assert stats2["existing"] == 1
    assert len(db.scalars(select(ResearchAlert)).all()) == 1


def test_emit_sin_redis_fail_open(db, monkeypatch):
    import app.workers.dramatiq_app as dapp

    monkeypatch.setattr(dapp, "_redis_client", lambda: None)
    stats = wd.emit_queue_stuck_alerts(db, now=NOW)
    assert stats["status"] == "skipped"
    assert stats["reason"] == "redis_unavailable"
