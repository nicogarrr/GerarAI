"""Atomic admission of new KPI work, using the installed Dramatiq Redis wire format.

Retries/promotions retain their normal broker path: admission must never discard
an already accepted job. Ready and delayed hashes include unacknowledged work.
"""
from __future__ import annotations

import os
from uuid import uuid4

from dramatiq.brokers.redis import RedisBroker


class QueueCapacityError(RuntimeError):
    """The document must remain deferred in Postgres, not be dropped."""


def max_pending() -> int:
    try:
        return max(1, int(os.getenv("KPI_QUEUE_MAX_PENDING", "100")))
    except ValueError:
        return 100


_ADMIT = """
local now = tonumber(redis.call('time')[1])
redis.call('zremrangebyscore', KEYS[4], '-inf', now - 61)
if redis.call('zcount', KEYS[4], now - 60, '+inf') == 0 then return -1 end
local depth = redis.call('hlen', KEYS[1]) + redis.call('hlen', KEYS[2])
if depth >= tonumber(ARGV[1]) then return 0 end
redis.call('hset', KEYS[1], ARGV[2], ARGV[3])
redis.call('rpush', KEYS[3], ARGV[2])
return 1
"""


class BoundedRedisBroker(RedisBroker):
    def consume(self, queue_name, **kwargs):
        consumer = super().consume(queue_name, **kwargs)
        if queue_name == "kpis":
            from app.workers.kpi_consumer_health import KPIConsumer

            return KPIConsumer(consumer, self.client, self.namespace, self.broker_id)
        return consumer

    def enqueue(self, message, *, delay=None):
        # DQ promotions carry eta; retry messages carry retries. Neither is
        # new ingestion, and blocking either would lose accepted work.
        if (message.queue_name != "kpis" or delay is not None
                or "retries" in message.options or "eta" in message.options):
            return super().enqueue(message, delay=delay)
        message = message.copy(options={"redis_message_id": str(uuid4())})
        self.emit_before("enqueue", message, delay)
        base = f"{self.namespace}:kpis"
        admitted = self.client.eval(
            _ADMIT, 4, f"{base}.msgs", f"{base}.DQ.msgs", base, f"{base}:consumers",
            max_pending(), message.options["redis_message_id"], message.encode(),
        )
        if admitted == -1:
            raise QueueCapacityError("Sin consumidor KPI activo; documento diferido")
        if not admitted:
            raise QueueCapacityError("La cola KPI esta llena; documento diferido")
        self.emit_after("enqueue", message, delay)
        return message
