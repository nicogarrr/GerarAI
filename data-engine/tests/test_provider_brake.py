"""Freno por proveedor en Redis (racha de 429 -> pausa con TTL, visible).

Orden de Nico (31-oct-2026): colas que no se atasquen. Invariantes:

1. Racha bajo el umbral no abre; al umbral abre con TTL y resetea la racha.
2. La ventana de la racha se pone solo en el primer incremento.
3. Un exito rompe la racha; el freno abierto caduca solo por TTL.
4. Redis caido es fail-open (sin freno, estado vacio).
5. open_brakes lista los frenos genericos y los legacy (gdelt, sec) con TTL.
6. Proveedor no registrado: ValueError explicito (registro obligatorio).
"""

from __future__ import annotations

import threading

import pytest

from app.services.provider_brake import (
    PROVIDER_BRAKES,
    is_open,
    open_brakes,
    record_429,
    record_success,
)


class FakeRedis:
    def __init__(self, raises=False):
        self.store = {}
        self.ttls = {}
        self.raises = raises
        self.lock = threading.Lock()

    def set(self, key, value, nx=False, ex=None):
        if self.raises:
            raise ConnectionError("redis caido")
        with self.lock:
            if nx and key in self.store:
                return None
            self.store[key] = value
            if ex is not None:
                self.ttls[key] = ex
            return True

    def get(self, key):
        if self.raises:
            raise ConnectionError("redis caido")
        with self.lock:
            return self.store.get(key)

    def delete(self, key):
        if self.raises:
            raise ConnectionError("redis caido")
        with self.lock:
            self.store.pop(key, None)

    def incr(self, key):
        if self.raises:
            raise ConnectionError("redis caido")
        with self.lock:
            self.store[key] = int(self.store.get(key, 0)) + 1
            return self.store[key]

    def expire(self, key, seconds):
        if self.raises:
            raise ConnectionError("redis caido")
        with self.lock:
            self.ttls[key] = seconds
        return True

    def ttl(self, key):
        if self.raises:
            raise ConnectionError("redis caido")
        return self.ttls.get(key, -1)


def test_streak_below_threshold_does_not_open():
    client = FakeRedis()
    cfg = PROVIDER_BRAKES["yahoo"]
    for _ in range(cfg.streak_limit - 1):
        assert record_429(client, "yahoo") is False
    assert is_open(client, "yahoo") is False
    # La ventana se fija en el primer incremento y no se renueva.
    assert client.ttls["provider_brake:yahoo:429_streak"] == cfg.window_s


def test_threshold_trips_brake_with_cooldown_and_resets_streak():
    client = FakeRedis()
    cfg = PROVIDER_BRAKES["google-news"]
    opened = [record_429(client, "google-news") for _ in range(cfg.streak_limit)]
    assert opened[-1] is True
    assert is_open(client, "google-news") is True
    assert client.ttls["provider_brake:google-news:open"] == cfg.cooldown_s
    assert "provider_brake:google-news:429_streak" not in client.store


def test_success_breaks_the_streak():
    client = FakeRedis()
    cfg = PROVIDER_BRAKES["yahoo"]
    for _ in range(cfg.streak_limit - 1):
        record_429(client, "yahoo")
    record_success(client, "yahoo")
    for _ in range(cfg.streak_limit - 1):
        assert record_429(client, "yahoo") is False
    assert is_open(client, "yahoo") is False


def test_providers_are_independent():
    client = FakeRedis()
    for _ in range(PROVIDER_BRAKES["yahoo"].streak_limit):
        record_429(client, "yahoo")
    assert is_open(client, "yahoo") is True
    assert is_open(client, "google-news") is False


def test_fail_open_when_redis_down():
    down = FakeRedis(raises=True)
    assert is_open(down, "yahoo") is False
    assert record_429(down, "yahoo") is False
    record_success(down, "yahoo")  # no lanza
    assert open_brakes(down) == []
    assert is_open(None, "yahoo") is False
    assert open_brakes(None) == []


def test_open_brakes_lists_generic_and_legacy_with_ttl():
    client = FakeRedis()
    record_429(client, "yahoo")
    record_429(client, "yahoo")
    record_429(client, "yahoo")
    client.set("gdelt:circuit:open", "1", ex=1700)
    client.set("sec_breaker:open", "1", ex=3500)
    brakes = {b["provider"]: b for b in open_brakes(client)}
    assert brakes["yahoo"]["ttl_seconds"] == PROVIDER_BRAKES["yahoo"].cooldown_s
    assert brakes["gdelt"]["ttl_seconds"] == 1700
    assert brakes["sec"]["ttl_seconds"] == 3500
    assert "google-news" not in brakes


def test_unregistered_provider_raises():
    with pytest.raises(ValueError):
        record_429(FakeRedis(), "proveedor-inventado")
    with pytest.raises(ValueError):
        is_open(FakeRedis(), "proveedor-inventado")


def test_data_sources_health_exposes_open_brakes(monkeypatch):
    """El estado del freno es visible en /health/data-sources (solo lectura)."""
    from app.api.routes import health

    monkeypatch.setattr(
        health, "get_data_source_registry",
        lambda: type("R", (), {"summary": lambda self: {"sources": []}})(),
    )
    monkeypatch.setattr(
        health, "get_alpha_vantage_client",
        lambda: type("Q", (), {"quota_status": lambda self: {"remaining": 25}})(),
    )
    client = FakeRedis()
    client.set("provider_brake:yahoo:open", "1", ex=1800)
    client.set("gdelt:circuit:open", "1", ex=900)
    monkeypatch.setattr("app.core.cache._redis_client", lambda: client)
    out = health.data_sources_health()
    providers = {b["provider"] for b in out["provider_brakes"]}
    assert providers == {"yahoo", "gdelt"}


def test_data_sources_health_brakes_fail_open(monkeypatch):
    from app.api.routes import health

    monkeypatch.setattr(
        health, "get_data_source_registry",
        lambda: type("R", (), {"summary": lambda self: {"sources": []}})(),
    )
    monkeypatch.setattr(
        health, "get_alpha_vantage_client",
        lambda: type("Q", (), {"quota_status": lambda self: {"remaining": 25}})(),
    )
    monkeypatch.setattr(
        "app.core.cache._redis_client",
        lambda: (_ for _ in ()).throw(ConnectionError("redis caido")),
    )
    assert health.data_sources_health()["provider_brakes"] == []
