"""Disyuntor GDELT compartido entre procesos.

Medido en prod (31-oct-2026, piloto): rachas de 3-16 respuestas 429 por IP y
Retry de 225-309 s que queman los hilos del carril gdelt sin progreso. El
disyuntor en Redis convierte la racha en una pausa de 30 min: los actores
skippean al entrar y el fan-out del scheduler queda pausado de facto.
"""

from __future__ import annotations

import threading

import dramatiq
import pytest

from app.workers import dramatiq_app
from app.workers.dramatiq_app import (
    GDELT_CIRCUIT_THRESHOLD,
    GDELT_CIRCUIT_TTL_SECONDS,
    _gdelt_429_recorded,
    _gdelt_circuit_open,
    _gdelt_success_recorded,
    _raise_gdelt_retry,
)


class FakeRedis:
    def __init__(self, raises=False):
        self.store = {}
        self.raises = raises
        self.lock = threading.Lock()

    def set(self, key, value, nx=False, ex=None):
        if self.raises:
            raise ConnectionError("redis caido")
        with self.lock:
            if nx and key in self.store:
                return None
            self.store[key] = value
            return True

    def get(self, key):
        with self.lock:
            return self.store.get(key)

    def delete(self, key):
        with self.lock:
            self.store.pop(key, None)

    def exists(self, key):
        if self.raises:
            raise ConnectionError("redis caido")
        with self.lock:
            return int(key in self.store)

    def incr(self, key):
        if self.raises:
            raise ConnectionError("redis caido")
        with self.lock:
            self.store[key] = int(self.store.get(key, 0)) + 1
            return self.store[key]

    def expire(self, key, seconds):
        if self.raises:
            raise ConnectionError("redis caido")
        return True

    def eval(self, script, numkeys, *args):
        key, token = args
        with self.lock:
            if self.store.get(key) == token:
                self.store.pop(key)
                return 1
            return 0


def _patch_client(monkeypatch, client):
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: client)


def test_streak_below_threshold_does_not_open(monkeypatch):
    client = FakeRedis()
    for _ in range(GDELT_CIRCUIT_THRESHOLD - 1):
        assert _gdelt_429_recorded(client) is False
    assert not _gdelt_circuit_open(client)


def test_threshold_trips_the_circuit_and_resets_streak(monkeypatch):
    client = FakeRedis()
    for _ in range(GDELT_CIRCUIT_THRESHOLD - 1):
        _gdelt_429_recorded(client)
    assert _gdelt_429_recorded(client) is True
    assert _gdelt_circuit_open(client)
    assert "gdelt:circuit:streak" not in client.store


def test_success_breaks_the_streak(monkeypatch):
    client = FakeRedis()
    for _ in range(GDELT_CIRCUIT_THRESHOLD - 1):
        _gdelt_429_recorded(client)
    _gdelt_success_recorded(client)
    for _ in range(GDELT_CIRCUIT_THRESHOLD - 1):
        assert _gdelt_429_recorded(client) is False
    assert not _gdelt_circuit_open(client)


def test_circuit_read_is_fail_open(monkeypatch):
    assert _gdelt_circuit_open(FakeRedis(raises=True)) is False
    assert _gdelt_circuit_open(None) is False


def test_retry_honors_server_window_below_threshold(monkeypatch):
    client = FakeRedis()
    _patch_client(monkeypatch, client)
    exc = Exception("429")
    exc.retry_after = 240.0
    with pytest.raises(dramatiq.Retry) as caught:
        _raise_gdelt_retry(exc)
    # Jitter: nunca antes de la ventana, como mucho un 20 % despues.
    assert 240_000 <= caught.value.delay < (240_000) * 1.2
    assert not _gdelt_circuit_open(client)


def test_retry_waits_the_circuit_ttl_once_open(monkeypatch):
    client = FakeRedis()
    _patch_client(monkeypatch, client)
    exc = Exception("429")
    exc.retry_after = 240.0
    delay = None
    for _ in range(GDELT_CIRCUIT_THRESHOLD):
        with pytest.raises(dramatiq.Retry) as caught:
            _raise_gdelt_retry(exc)
        delay = caught.value.delay
    # Jitter: nunca antes de la ventana, como mucho un 20 % despues.
    assert GDELT_CIRCUIT_TTL_SECONDS * 1000 <= delay < (GDELT_CIRCUIT_TTL_SECONDS * 1000) * 1.2
    assert _gdelt_circuit_open(client)


def test_refresh_news_skips_fast_while_circuit_open(monkeypatch):
    client = FakeRedis()
    client.set("gdelt:circuit:open", "1")
    _patch_client(monkeypatch, client)
    result = dramatiq_app.refresh_news.fn(None, None)
    assert result["status"] == "skipped"
    assert result["reason"] == "gdelt_circuit_open"


def test_refresh_macro_news_skips_fast_while_circuit_open(monkeypatch):
    client = FakeRedis()
    client.set("gdelt:circuit:open", "1")
    _patch_client(monkeypatch, client)
    result = dramatiq_app.refresh_macro_news.fn(None, None)
    assert result["status"] == "skipped"
    assert result["reason"] == "gdelt_circuit_open"


def test_retry_message_is_rescheduled_not_acked(monkeypatch):
    """Bloqueo del piloto: un retry/eta nunca se ack sin trabajo con el
    disyuntor abierto: se reprograma tras el TTL y el claim se libera."""
    import time
    from types import SimpleNamespace

    client = FakeRedis()
    client.set("gdelt:circuit:open", "1")
    _patch_client(monkeypatch, client)
    retry_msg = SimpleNamespace(
        options={"retries": 2}, message_timestamp=time.time() * 1000
    )
    monkeypatch.setattr(
        dramatiq_app.CurrentMessage,
        "get_current_message",
        classmethod(lambda cls: retry_msg),
    )
    with pytest.raises(dramatiq.Retry) as caught:
        dramatiq_app.refresh_news.fn(None, None)
    # Jitter: nunca antes de la ventana, como mucho un 20 % despues.
    assert GDELT_CIRCUIT_TTL_SECONDS * 1000 <= caught.value.delay < (GDELT_CIRCUIT_TTL_SECONDS * 1000) * 1.2
    # El claim del coalescer se libera: el lote reprogramado puede reclamar.
    assert "coalesce:refresh_news:None" not in client.store


def test_delayed_message_is_rescheduled_not_acked(monkeypatch):
    import time
    from types import SimpleNamespace

    client = FakeRedis()
    client.set("gdelt:circuit:open", "1")
    _patch_client(monkeypatch, client)
    eta_msg = SimpleNamespace(options={"eta": 123}, message_timestamp=time.time() * 1000)
    monkeypatch.setattr(
        dramatiq_app.CurrentMessage,
        "get_current_message",
        classmethod(lambda cls: eta_msg),
    )
    with pytest.raises(dramatiq.Retry):
        dramatiq_app.refresh_macro_news.fn(None, None)


def test_server_window_longer_than_circuit_ttl_wins(monkeypatch):
    """Bloqueo del piloto: al abrirse el disyuntor el delay es
    max(retry_after del servidor, TTL del disyuntor)."""
    client = FakeRedis()
    _patch_client(monkeypatch, client)
    exc = Exception("429")
    exc.retry_after = 3600.0  # ventana de 1 h > TTL de 30 min
    delay = None
    for _ in range(GDELT_CIRCUIT_THRESHOLD):
        with pytest.raises(dramatiq.Retry) as caught:
            _raise_gdelt_retry(exc)
        delay = caught.value.delay
    assert _gdelt_circuit_open(client)
    # Jitter: nunca antes de la ventana, como mucho un 20 % despues.
    assert 3_600_000 <= delay < (3_600_000) * 1.2
