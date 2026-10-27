"""Carrera: el lease local de jobs (sin Redis) debe excluir a hilos concurrentes."""

from __future__ import annotations

import threading
import time

from app.workers import dramatiq_app


class _SlowGetDict(dict):
    """Ensancha la ventana entre comprobar y escribir para forzar el solape."""

    def get(self, key, default=None):
        value = super().get(key, default)
        time.sleep(0.05)
        return value


def test_local_job_lease_admits_a_single_thread(monkeypatch):
    monkeypatch.setattr(dramatiq_app, "_local_leases", _SlowGetDict())
    n = 8
    barrier = threading.Barrier(n)
    tokens: list = [None] * n

    def run(i):
        barrier.wait(timeout=10)
        tokens[i] = dramatiq_app.acquire_job_lease("job-x", ttl_seconds=60, redis_url=None)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sum(1 for t in tokens if t) == 1, tokens
