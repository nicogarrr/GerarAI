"""Bordes de ``app.core.replay``: consume_nonce con Redis, local y reset.

Lo que cada test demuestra:
- Con Redis (fake): ``set nx ex`` con los argumentos exactos; True si se
  adquiere, False si el nonce ya existia (43-50).
- Redis caido con ``allow_local_fallback=False`` lanza
  NonceBackendUnavailable (52-55); con fallback degrada al cache local.
- El cache local purga claves caducadas (61), rechaza el nonce repetido (63)
  y ``reset_local_nonces`` lo vacia (68-70).

El estado global ``_local_nonces`` se restaura al salir de cada test.
"""

from __future__ import annotations

import asyncio

import pytest

import app.core.replay as replay
from app.core.replay import (
    NonceBackendUnavailable,
    _local_nonces,
    consume_nonce,
    reset_local_nonces,
)


class _Client:
    def __init__(self, result):
        self._result = result
        self.set_args = None

    async def set(self, *a, **kw):
        self.set_args = (a, kw)
        return self._result


class _RedisCM:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, *a):
        return False


def _redis_down(url):
    raise OSError("store unreachable")


@pytest.fixture
def preserve_nonces():
    prior = dict(_local_nonces)
    try:
        yield
    finally:
        _local_nonces.clear()
        _local_nonces.update(prior)


def test_redis_adquiere_con_argumentos_exactos(monkeypatch, preserve_nonces):
    client = _Client(True)
    monkeypatch.setattr("app.core.redis_client.short_async_redis", lambda url: _RedisCM(client))
    ok = asyncio.run(consume_nonce("replay:k1", ttl_seconds=30, redis_url="redis://x"))
    assert ok is True
    assert client.set_args == (("replay:k1", "1"), {"nx": True, "ex": 30})


def test_redis_nonce_ya_consumido(monkeypatch, preserve_nonces):
    client = _Client(None)
    monkeypatch.setattr("app.core.redis_client.short_async_redis", lambda url: _RedisCM(client))
    ok = asyncio.run(consume_nonce("replay:k1", ttl_seconds=30, redis_url="redis://x"))
    assert ok is False


def test_redis_caido_sin_fallback_lanza(monkeypatch, preserve_nonces):
    monkeypatch.setattr("app.core.redis_client.short_async_redis", _redis_down)
    with pytest.raises(NonceBackendUnavailable, match="nonce store unreachable"):
        asyncio.run(
            consume_nonce("replay:k1", ttl_seconds=30, redis_url="redis://x", allow_local_fallback=False)
        )


def test_redis_caido_con_fallback_degrada_a_local(monkeypatch, preserve_nonces):
    monkeypatch.setattr("app.core.redis_client.short_async_redis", _redis_down)
    assert asyncio.run(consume_nonce("replay:k2", ttl_seconds=30, redis_url="redis://x")) is True
    assert asyncio.run(consume_nonce("replay:k2", ttl_seconds=30, redis_url="redis://x")) is False


def test_local_purga_caducadas_y_rechaza_repetido(monkeypatch, preserve_nonces):
    monkeypatch.setattr(replay.time, "time", lambda: 1000.0)
    _local_nonces["replay:old"] = 900.0  # caducada (expira <= ahora)
    _local_nonces["replay:keep"] = 2000.0  # vigente
    assert asyncio.run(consume_nonce("replay:new", ttl_seconds=30, redis_url="", use_redis=False)) is True
    assert "replay:old" not in _local_nonces
    assert _local_nonces["replay:keep"] == 2000.0
    assert _local_nonces["replay:new"] == 1030.0
    # Repetido dentro de la ventana: rechazado.
    assert asyncio.run(consume_nonce("replay:new", ttl_seconds=30, redis_url="", use_redis=False)) is False


def test_reset_local_nonces_vacia(preserve_nonces):
    _local_nonces["replay:a"] = 1.0
    _local_nonces["replay:b"] = 2.0
    reset_local_nonces()
    assert dict(_local_nonces) == {}
