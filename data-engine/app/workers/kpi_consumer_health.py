"""Queue-specific lease refreshed only by successful KPI consumer polling.

A live PID, old ack or another queue's broker heartbeat is not a KPI consumer.
This measures polling liveness, not task completion: progress remains a separate
queue-watchdog concern. Redis time is authoritative across processes.
"""
from __future__ import annotations

from pathlib import Path

LEASE_SECONDS = 60
TOKEN_PATH = Path('/tmp/gerarai-kpi-consumer-id')


def consumer_key(namespace: str) -> str:
    return f"{namespace}:kpis:consumers"


def healthy(client, namespace: str, token: str) -> bool:
    score = client.zscore(consumer_key(namespace), token)
    return score is not None and float(score) >= int(client.time()[0]) - LEASE_SECONDS


class KPIConsumer:
    def __init__(self, consumer, client, namespace: str, token: str):
        self.consumer = consumer
        self.client = client
        self.namespace = namespace
        self.token = token

    def __getattr__(self, name):
        return getattr(self.consumer, name)

    def __iter__(self):
        return self

    def __next__(self):
        message = next(self.consumer)  # Failure must not renew the lease.
        self.client.zadd(consumer_key(self.namespace), {self.token: int(self.client.time()[0])})
        # Local token binds healthcheck to THIS worker, not some other host.
        if not TOKEN_PATH.exists() or TOKEN_PATH.read_text() != self.token:
            TOKEN_PATH.write_text(self.token)
        return message

    def close(self):
        try:
            self.client.zrem(consumer_key(self.namespace), self.token)
        finally:
            self.consumer.close()


def main() -> int:
    import redis

    from app.core.config import get_settings
    from app.core.redis_retry import no_retry

    try:
        client = redis.Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=3, socket_timeout=3, retry=no_retry(),
        )
        return 0 if healthy(client, 'dramatiq', TOKEN_PATH.read_text()) else 1
    except Exception:
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
