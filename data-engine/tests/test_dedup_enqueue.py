"""Dedup de encolado de periodicos de ingesta (BoundedRedisBroker + middleware).

Medido en prod (31-oct): default con 8.709 pendientes, p50 39 h; muestra de
1.000: 109 RSS + 90 insider + 48 ticker_news + ... = re-encolados periodicos
con copia identica ya pendiente. Con dedup_enqueue_ttl, como mucho UNA copia
identica (actor+args+kwargs) espera en cola; la marca se libera al consumir
y caduca por TTL si el mensaje muere sin consumirse.

Invariantes:
1. Primer envio pasa al broker real; el duplicado identico NO entra en cola.
2. Reintentos (retries) y diferidos (eta/delay) nunca se bloquean.
3. before_process_message libera la marca: el siguiente tick encola de nuevo.
4. Redis caido es fail-open: encola siempre.
"""

from __future__ import annotations

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.workers.bounded_broker import (
    DEDUP_ENQUEUE_OPTION,
    BoundedRedisBroker,
    DedupEnqueueMiddleware,
    dedup_mark_key,
)


class FakeRedis:
    def __init__(self, raises=False):
        self.store = {}
        self.raises = raises

    def register_script(self, script):
        return script

    def set(self, key, value, nx=False, ex=None):
        if self.raises:
            raise ConnectionError("redis caido")
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, key):
        self.store.pop(key, None)


def _actor(broker, ttl=7200):
    @dramatiq.actor(queue_name="default", **({} if ttl is None else {DEDUP_ENQUEUE_OPTION: ttl}))
    def probe(tenant_id, scope="tracked"):
        return None

    return probe


def _broker(client):
    broker = BoundedRedisBroker(client=client)
    broker.add_middleware(DedupEnqueueMiddleware())
    dramatiq.set_broker(broker)
    return broker


def _passthrough_count(monkeypatch):
    calls = []
    monkeypatch.setattr(RedisBroker, "enqueue", lambda self, message, *, delay=None: calls.append((message, delay)) or message)
    return calls


def test_clave_determinista_y_por_argumentos():
    k1 = dedup_mark_key("dramatiq", "refresh_rss_feeds", (2,), {})
    k2 = dedup_mark_key("dramatiq", "refresh_rss_feeds", (2,), {})
    k3 = dedup_mark_key("dramatiq", "refresh_rss_feeds", (3,), {})
    assert k1 == k2 and k1 != k3 and "refresh_rss_feeds" in k1


def test_primer_envio_pasa_y_duplicado_identico_no_entra(monkeypatch):
    client = FakeRedis()
    broker = _broker(client)
    actor = _actor(broker)
    calls = _passthrough_count(monkeypatch)

    broker.enqueue(actor.message(2))
    assert len(calls) == 1, "el primero llega a la cola"
    broker.enqueue(actor.message(2))
    assert len(calls) == 1, "duplicado identico con copia pendiente: no entra"
    broker.enqueue(actor.message(3))
    assert len(calls) == 2, "argumentos distintos = trabajo distinto: entra"


def test_reintentos_y_diferidos_nunca_se_bloquean(monkeypatch):
    client = FakeRedis()
    broker = _broker(client)
    actor = _actor(broker)
    calls = _passthrough_count(monkeypatch)

    broker.enqueue(actor.message(2))
    retry = actor.message(2).copy(options={"retries": 1})
    broker.enqueue(retry)
    broker.enqueue(actor.message(2), delay=60_000)
    assert len(calls) == 3, "retry y delayed conservan su camino normal"


def test_actor_sin_opcion_no_deduplica(monkeypatch):
    client = FakeRedis()
    broker = _broker(client)
    actor = _actor(broker, ttl=None)
    calls = _passthrough_count(monkeypatch)
    broker.enqueue(actor.message(2))
    broker.enqueue(actor.message(2))
    assert len(calls) == 2


def test_consumir_libera_la_marca_y_el_siguiente_tick_encola(monkeypatch):
    client = FakeRedis()
    broker = _broker(client)
    actor = _actor(broker)
    calls = _passthrough_count(monkeypatch)

    broker.enqueue(actor.message(2))
    assert len(calls) == 1
    mw = DedupEnqueueMiddleware()
    mw.before_process_message(broker, actor.message(2))
    broker.enqueue(actor.message(2))
    assert len(calls) == 2, "tras consumir, el siguiente tick encola de nuevo"


def test_redis_caido_es_fail_open(monkeypatch):
    client = FakeRedis(raises=True)
    broker = _broker(client)
    actor = _actor(broker)
    calls = _passthrough_count(monkeypatch)
    broker.enqueue(actor.message(2))
    broker.enqueue(actor.message(2))
    assert len(calls) == 2, "con Redis roto se encola igual (un duplicado lo absorbe el claim)"
