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


def test_drenaje_parcial_conserva_la_edad_del_mas_antiguo(redis_client):
    """El agujero del lunes: la cabeza avanza (drenaje parcial) pero el
    mensaje que la releva YA fue visto listo: su edad no vuelve a 0."""
    _push(redis_client, "prices")
    _push(redis_client, "prices")
    t0 = NOW.timestamp() * 1000
    wd.sample_queues(redis_client, queues=("prices",), now_ms=t0)  # avistamiento
    # Se consume SOLO la cabeza (drenaje parcial): el relevo ya era conocido.
    mid = redis_client.lpop("dramatiq:prices")
    redis_client.hdel("dramatiq:prices.msgs", mid)
    (sample,) = wd.sample_queues(redis_client, queues=("prices",), now_ms=t0 + 400_000)
    assert sample.ready_age_seconds == 400.0  # no 0: el relevo llevaba 400 s listo


def test_mensaje_joven_no_reinicia_la_edad_del_mas_antiguo(redis_client):
    _push(redis_client, "prices")
    t0 = NOW.timestamp() * 1000
    wd.sample_queues(redis_client, queues=("prices",), now_ms=t0)
    _push(redis_client, "prices")  # mensaje nuevo al final (FIFO)
    (sample,) = wd.sample_queues(redis_client, queues=("prices",), now_ms=t0 + 60_000)
    assert sample.ready_age_seconds == 60.0  # manda el más antiguo


def test_cola_vacia_borra_la_anotacion(redis_client):
    _push(redis_client, "prices")
    wd.sample_queues(redis_client, queues=("prices",), now_ms=NOW.timestamp() * 1000)
    mid = redis_client.lpop("dramatiq:prices")
    redis_client.hdel("dramatiq:prices.msgs", mid)
    (sample,) = wd.sample_queues(
        redis_client, queues=("prices",), now_ms=NOW.timestamp() * 1000 + 120_000
    )
    assert sample.ready_age_seconds is None
    assert redis_client.get(f"{wd._SEEN_PREFIX}prices") is None


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


# --- Trabajo en vuelo de workers con heartbeat fresco ------------------------

def _heartbeat(client, worker: str, *, at_ms: float, namespace: str = "dramatiq"):
    client.zadd(f"{namespace}:__heartbeats__", {worker: at_ms})


def test_en_vuelo_suma_workers_con_heartbeat_fresco_sin_cruzar_colas(redis_client):
    now_ms = NOW.timestamp() * 1000
    redis_client.sadd("dramatiq:__acks__.w1.yahoo", "a", "b")
    redis_client.sadd("dramatiq:__acks__.w2.yahoo", "c")
    redis_client.sadd("dramatiq:__acks__.w1.prices", "z")
    redis_client.sadd("dramatiq:__acks__.muerto.yahoo", "huerfano")
    _heartbeat(redis_client, "w1", at_ms=now_ms)
    _heartbeat(redis_client, "w2", at_ms=now_ms - 30_000)  # fresco (< 60 s)
    _heartbeat(redis_client, "muerto", at_ms=now_ms - 120_000)  # vencido
    count = wd._in_flight_count(redis_client, namespace="dramatiq", queue="yahoo", now_ms=now_ms)
    assert count == 3  # w1 + w2; el ack huerfano del worker muerto NO cuenta
    assert wd._in_flight_count(redis_client, namespace="dramatiq", queue="prices", now_ms=now_ms) == 1
    assert wd._in_flight_count(redis_client, namespace="dramatiq", queue="gdelt", now_ms=now_ms) == 0


def test_en_vuelo_respeta_el_env_de_timeout_de_heartbeat(redis_client, monkeypatch):
    now_ms = NOW.timestamp() * 1000
    redis_client.sadd("dramatiq:__acks__.w1.yahoo", "a")
    _heartbeat(redis_client, "w1", at_ms=now_ms - 5_000)
    monkeypatch.setenv("QUEUE_WATCHDOG_WORKER_HEARTBEAT_TIMEOUT_MS", "10000")
    assert wd._in_flight_count(redis_client, namespace="dramatiq", queue="yahoo", now_ms=now_ms) == 1
    monkeypatch.setenv("QUEUE_WATCHDOG_WORKER_HEARTBEAT_TIMEOUT_MS", "1000")
    assert wd._in_flight_count(redis_client, namespace="dramatiq", queue="yahoo", now_ms=now_ms) == 0


def test_detect_stuck_no_alerta_con_trabajo_en_vuelo_bajo_el_techo():
    # Barrido largo en marcha (p. ej. yahoo scope=all, ~34 min medido en prod
    # el 09-nov-2026): la cabeza ready envejece y la profundidad neta no
    # decrece, pero hay trabajo en vuelo de un worker con heartbeat fresco y
    # la cabeza esta bajo el techo duro -> no es atasco.
    now = time.time()
    prev = {"yahoo": {"ts": now - 300, "depth": 10.0}}
    samples = [wd.QueueSample(queue="yahoo", depth=12, ready_age_seconds=1000.0, in_flight=1)]
    assert wd.detect_stuck(samples, prev, max_age=900.0, now=now) == []


def test_detect_stuck_alerta_con_trabajo_en_vuelo_sobre_el_techo():
    # Cabeza de 5 h con trabajo en vuelo: por encima del techo (4 h) ni el
    # heartbeat fresco absuelve (posible worker colgado reteniendo acks).
    now = time.time()
    prev = {"yahoo": {"ts": now - 300, "depth": 10.0}}
    samples = [wd.QueueSample(queue="yahoo", depth=12, ready_age_seconds=5 * 3600.0, in_flight=3)]
    (stuck,) = wd.detect_stuck(samples, prev, max_age=900.0, now=now)
    assert stuck["queue"] == "yahoo"
    assert stuck["in_flight"] == 3  # metadata de diagnostico


def test_tick_no_marca_atascada_con_trabajo_en_vuelo_fresco(redis_client, monkeypatch):
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_SAMPLE_GAP_SECONDS", "3600")
    _push(redis_client, "yahoo")
    wd.sample_tick(redis_client, namespace="dramatiq", queues=("yahoo",), now=NOW)
    now_ms = (NOW + timedelta(seconds=1200)).timestamp() * 1000
    redis_client.sadd("dramatiq:__acks__.w1.yahoo", "m1")
    _heartbeat(redis_client, "w1", at_ms=now_ms)
    result = wd.sample_tick(redis_client, namespace="dramatiq", queues=("yahoo",),
                            now=NOW + timedelta(seconds=1200))
    assert result["stuck"] == []


def test_tick_marca_atascada_la_misma_cola_sin_trabajo_en_vuelo(redis_client, monkeypatch):
    # Control: el mismo escenario sin trabajo en vuelo SI se marca atascada.
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_SAMPLE_GAP_SECONDS", "3600")
    _push(redis_client, "yahoo")
    wd.sample_tick(redis_client, namespace="dramatiq", queues=("yahoo",), now=NOW)
    result = wd.sample_tick(redis_client, namespace="dramatiq", queues=("yahoo",),
                            now=NOW + timedelta(seconds=1200))
    assert [item["queue"] for item in result["stuck"]] == ["yahoo"]


def test_tick_marca_atascada_con_ack_huerfano_de_worker_muerto(redis_client, monkeypatch):
    # Escenario del auditor: worker muerto con acks y sin heartbeat (o con el
    # vencido) NO absuelve: sus acks huerfanos no cuentan como en vuelo.
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_SAMPLE_GAP_SECONDS", "3600")
    _push(redis_client, "yahoo")
    wd.sample_tick(redis_client, namespace="dramatiq", queues=("yahoo",), now=NOW)
    redis_client.sadd("dramatiq:__acks__.muerto.yahoo", "m1", "m2")
    # Sin entrada en __heartbeats__: el worker ya no existe para el broker.
    result = wd.sample_tick(redis_client, namespace="dramatiq", queues=("yahoo",),
                            now=NOW + timedelta(seconds=1200))
    assert [item["queue"] for item in result["stuck"]] == ["yahoo"]
    # Con heartbeat vencido (> 60 s), tampoco.
    redis_client.delete(wd._SAMPLE_PREFIX + "yahoo")
    wd.sample_tick(redis_client, namespace="dramatiq", queues=("yahoo",), now=NOW)
    _heartbeat(redis_client, "muerto", at_ms=(NOW + timedelta(seconds=1200)).timestamp() * 1000 - 120_000)
    result = wd.sample_tick(redis_client, namespace="dramatiq", queues=("yahoo",),
                            now=NOW + timedelta(seconds=1200))
    assert [item["queue"] for item in result["stuck"]] == ["yahoo"]


# --- Punto 1: una medición por tick aunque el actor corra por tenant ---------

def test_una_medicion_por_tick_los_demas_tenants_reusan(db, redis_client, monkeypatch):
    # Ticks separados 1000 s: hueco maximo por encima para que el avistamiento
    # no expire entre ticks (el default 600 cortaria la continuidad).
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_SAMPLE_GAP_SECONDS", "3600")
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

def test_emit_crea_alerta_idempotente_con_lo_medido(db, redis_client, monkeypatch):
    # Ticks separados 1000 s: hueco maximo por encima para que el avistamiento
    # no expire (el default 600 cortaria la continuidad entre ambos ticks).
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_SAMPLE_GAP_SECONDS", "3600")
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
    # La fuente de verdad es el broker en vivo: importar dramatiq_app registra
    # todos los actores (incl. knowledge_rag_actors y thesis_track_record_actors,
    # que el propio modulo importa) y con ellos sus colas. La lista manual que
    # habia aqui se quedo en 11 colas mientras nacian documents, official-closes,
    # dca-manual e ibkr-sync: el fallback estatico no las vigilaba y el test
    # pasaba igual. Igualdad exacta (no subconjunto): una cola borrada del
    # broker tambien debe salir del fallback.
    import app.workers.dramatiq_app as dapp

    declared = set(dapp.broker.get_declared_queues())
    assert declared == set(wd.DEFAULT_QUEUES)


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


# --- Auditoría v3: huecos de muestreo y backlog > ventana --------------------

def test_hueco_de_muestreo_expira_el_avistamiento(redis_client, monkeypatch):
    """Watchdog apagado un rato: no se afirma 'ready continuo' durante el hueco.

    Si entre dos ticks pasa más que el hueco máximo, el avistamiento previo no
    prueba continuidad (el mensaje pudo consumirse y reinsertarse con el mismo
    id): la edad vuelve a empezar en la reanudación.
    """
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_SAMPLE_GAP_SECONDS", "600")
    _push(redis_client, "prices")
    t0 = NOW.timestamp() * 1000
    wd.sample_queues(redis_client, queues=("prices",), now_ms=t0)
    # Hueco de 1200 s (> 600): la edad NO es 1200, reinicia.
    (sample,) = wd.sample_queues(redis_client, queues=("prices",), now_ms=t0 + 1_200_000)
    assert sample.ready_age_seconds == 0.0
    # Y a partir de la reanudación acumula normal.
    (sample,) = wd.sample_queues(redis_client, queues=("prices",), now_ms=t0 + 1_200_000 + 60_000)
    assert sample.ready_age_seconds == 60.0


def test_reinsertado_mismo_id_tras_ausencia_reinicia_edad(redis_client):
    """Extraído y reinsertado con el mismo id: si faltó en un tick, su
    avistamiento se podó y vuelve como avistamiento nuevo (edad 0)."""
    mid = _push(redis_client, "prices")
    t0 = NOW.timestamp() * 1000
    wd.sample_queues(redis_client, queues=("prices",), now_ms=t0)
    # Ausente un tick entero (consumido).
    redis_client.lrem("dramatiq:prices", 1, mid)
    redis_client.hdel("dramatiq:prices.msgs", mid)
    wd.sample_queues(redis_client, queues=("prices",), now_ms=t0 + 300_000)
    # Reinsertado con el MISMO id (retry que conserva message_id).
    redis_client.hset("dramatiq:prices.msgs", mid, json.dumps({"message_id": mid, "message_timestamp": 1}))
    redis_client.rpush("dramatiq:prices", mid)
    (sample,) = wd.sample_queues(redis_client, queues=("prices",), now_ms=t0 + 600_000)
    assert sample.ready_age_seconds == 0.0


def test_backlog_mayor_que_la_ventana_subestima_documentado(redis_client, monkeypatch):
    """Con backlog > K, un id más allá de la ventana no se avista hasta entrar:
    su edad empieza al entrar (subestimación mayor que un tick, documentada).
    El más antiguo siempre está en la ventana y su edad es continua."""
    monkeypatch.setattr(wd, "_SEEN_WINDOW", 3)
    t0 = NOW.timestamp() * 1000
    ids = [_push(redis_client, "prices") for _ in range(5)]
    wd.sample_queues(redis_client, queues=("prices",), now_ms=t0)  # avista los 3 más viejos
    # Drenar 3: los dos jóvenes entran en la ventana por primera vez a los 300 s.
    for mid in ids[:3]:
        redis_client.lrem("dramatiq:prices", 1, mid)
        redis_client.hdel("dramatiq:prices.msgs", mid)
    (sample,) = wd.sample_queues(redis_client, queues=("prices",), now_ms=t0 + 300_000)
    # El más antiguo restante (4º) entra ahora en ventana: edad 0 aunque
    # llevaba 300 s listo (subestimación > 1 tick por backlog > K).
    assert sample.ready_age_seconds == 0.0
    # Y desde ahí acumula.
    (sample,) = wd.sample_queues(redis_client, queues=("prices",), now_ms=t0 + 360_000)
    assert sample.ready_age_seconds == 60.0


def test_kpis_sin_consumidor_lo_dice_explicitamente(db, redis_client, monkeypatch):
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_SAMPLE_GAP_SECONDS", "3600")
    _push(redis_client, "kpis")
    wd.sample_tick(redis_client, namespace="dramatiq", queues=("kpis",), now=NOW - timedelta(seconds=1000))
    stats = wd.emit_queue_stuck_alerts(db, client=redis_client, now=NOW)
    assert stats["stuck"] == 1
    alert = db.scalars(select(ResearchAlert)).one()
    assert "sin consumidor" in alert.title.lower()
    assert "NINGUN consumidor" in alert.message
    assert alert.metadata_["no_consumer"] is True


def test_kpis_con_consumidor_fresco_usa_el_mensaje_generico(db, redis_client, monkeypatch):
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_SAMPLE_GAP_SECONDS", "3600")
    _push(redis_client, "kpis")
    redis_client.zadd("dramatiq:kpis:consumers", {"tok": int(NOW.timestamp()) - 5})
    wd.sample_tick(redis_client, namespace="dramatiq", queues=("kpis",), now=NOW - timedelta(seconds=1000))
    redis_client.zadd("dramatiq:kpis:consumers", {"tok": int(NOW.timestamp()) - 5})
    wd.emit_queue_stuck_alerts(db, client=redis_client, now=NOW)
    alert = db.scalars(select(ResearchAlert)).one()
    assert alert.title == "Cola kpis atascada"
    assert "variacion neta" in alert.message


def test_otras_colas_nunca_afirman_sin_consumidor(redis_client):
    _push(redis_client, "yahoo")
    samples = wd.sample_queues(redis_client, queues=("yahoo",), now_ms=NOW.timestamp() * 1000)
    assert samples[0].no_consumer is False


def test_kpis_redis_falla_al_medir_consumidor_no_afirma_ausencia(redis_client):
    _push(redis_client, "kpis")

    class BrokenZcount:
        def __getattr__(self, name):
            return getattr(redis_client, name)

        def zcount(self, *args, **kwargs):
            raise ConnectionError("redis caido")

    samples = wd.sample_queues(BrokenZcount(), queues=("kpis",), now_ms=NOW.timestamp() * 1000)
    assert samples[0].depth == 1
    assert samples[0].no_consumer is False
