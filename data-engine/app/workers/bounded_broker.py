"""Atomic admission of new KPI work, using Dramatiq 1.x Redis wire format.

Retries/promotions retain their normal broker path: admission must never discard
an already accepted job. Ready and delayed hashes include unacknowledged work.

Tambien vive aqui la DEDUPLICACION DE ENCOLADO de los periodicos de ingesta:
bajo backlog (31-oct: default con 8.709 pendientes, p50 39 h) el scheduler
re-encolaba cada tick aunque ya hubiera una copia identica esperando (muestra
de 1.000: 109 RSS + 90 insider + 48 ticker_news + ... de churn). Un actor con
la opcion ``dedup_enqueue_ttl`` admite como maximo UNA copia identica
(mismo actor, args y kwargs) pendiente; la marca se borra al consumir y
caduca por TTL como red de seguridad si el mensaje muere sin consumirse.
"""
from __future__ import annotations

import hashlib
import json
import os
from uuid import uuid4

from dramatiq.brokers.redis import RedisBroker
from dramatiq.errors import ActorNotFound
from dramatiq.middleware import Middleware

# Opcion de actor (segundos). Presencia = deduplicar encolados identicos.
DEDUP_ENQUEUE_OPTION = "dedup_enqueue_ttl"

# TTL por defecto: 2 h acotan el bloqueo si un mensaje muere sin consumirse
# (red de seguridad; lo normal es que se borre al consumir). Con backlog,
# un job de cadencia 15 min pasa de 96 copias/dia a <=12.
DEDUP_ENQUEUE_TTL_SECONDS = 2 * 60 * 60


def dedup_mark_key(namespace: str, actor_name: str, args, kwargs) -> str:
    """Clave de la marca "ya hay una copia identica en cola" (determinista)."""
    canonical = json.dumps([actor_name, list(args), kwargs], sort_keys=True, default=str)
    digest = hashlib.sha1(canonical.encode()).hexdigest()[:16]
    return f"{namespace}:dedup_enq:{actor_name}:{digest}"


class DedupEnqueueMiddleware(Middleware):
    """Declara la opcion y libera la marca al consumir el mensaje."""

    @property
    def actor_options(self):
        return {DEDUP_ENQUEUE_OPTION}

    def before_process_message(self, broker, message):
        # Sin borrarla, el siguiente tick tras consumir veria la marca viva y
        # no encolaria: el periodico quedaria mudo hasta el TTL.
        try:
            actor = broker.get_actor(message.actor_name)
        except ActorNotFound:
            return
        if not actor.options.get(DEDUP_ENQUEUE_OPTION):
            return
        # nosemgrep: gerarai-broad-except-pass -- lock/cola Redis best-effort con caducidad por TTL o fallback local documentado
        try:
            broker.client.delete(
                dedup_mark_key(broker.namespace, message.actor_name, message.args, message.kwargs)
            )
        except Exception:  # noqa: BLE001 - expira por TTL solo
            pass


class QueueCapacityError(RuntimeError):
    """The document must remain deferred in Postgres, not be dropped."""


def max_pending() -> int:
    try:
        return max(1, int(os.getenv("KPI_QUEUE_MAX_PENDING", "500")))
    except ValueError:
        return 500


_ADMIT = """
local depth = redis.call('hlen', KEYS[1]) + redis.call('hlen', KEYS[2])
if depth >= tonumber(ARGV[1]) then return 0 end
redis.call('hset', KEYS[1], ARGV[2], ARGV[3])
redis.call('rpush', KEYS[3], ARGV[2])
return 1
"""


class BoundedRedisBroker(RedisBroker):
    def enqueue(self, message, *, delay=None):
        # DQ promotions carry eta; retry messages carry retries. Neither is
        # new ingestion, and blocking either would lose accepted work.
        if delay is None and "retries" not in message.options and "eta" not in message.options:
            try:
                ttl = self.get_actor(message.actor_name).options.get(DEDUP_ENQUEUE_OPTION)
            except ActorNotFound:
                ttl = None
            if ttl:
                # Fail-open: con Redis roto se encola igual; un duplicado lo
                # absorbe el claim del actor y perder el trabajo seria peor.
                try:
                    claimed = self.client.set(
                        dedup_mark_key(self.namespace, message.actor_name, message.args, message.kwargs),
                        "1", nx=True, ex=max(int(ttl), 1),
                    )
                except Exception:  # noqa: BLE001 - sonda best-effort, fail-open
                    claimed = True
                if not claimed:
                    # Copia identica ya pendiente: el duplicado no entra en la
                    # cola. Sin emit_before/after: el mensaje nunca se acepta.
                    return message
        if (message.queue_name != "kpis" or delay is not None
                or "retries" in message.options or "eta" in message.options):
            return super().enqueue(message, delay=delay)
        message = message.copy(options={"redis_message_id": str(uuid4())})
        self.emit_before("enqueue", message, delay)
        base = f"{self.namespace}:kpis"
        admitted = self.client.eval(
            _ADMIT, 3, f"{base}.msgs", f"{base}.DQ.msgs", base,
            max_pending(), message.options["redis_message_id"], message.encode(),
        )
        if not admitted:
            raise QueueCapacityError("La cola KPI esta llena; documento diferido")
        self.emit_after("enqueue", message, delay)
        return message
