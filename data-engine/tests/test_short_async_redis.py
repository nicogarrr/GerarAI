"""short_async_redis: un solo cliente async de vida corta para las guardas.

rate_limit (dos sitios) y replay llevaban copiado el mismo bloque: cliente
redis.asyncio con timeouts 1.0/1.5 y retry=no_retry_async(), uso, y cierre
con aclose() en finally. Vive ahora en core/redis_client.py. Se fija su
contrato y que los dos modulos no reintroducen su copia.
"""

import asyncio
from pathlib import Path

import pytest

from app.core.redis_client import short_async_redis


class _FakeClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture()
def fake(monkeypatch):
    calls: list[dict] = {}
    client = _FakeClient()

    def _from_url(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return client

    import redis.asyncio as redis_async

    monkeypatch.setattr(redis_async, "from_url", _from_url)
    return client, calls


def test_parametros_y_cierre(fake):
    client, calls = fake

    async def _run():
        async with short_async_redis("redis://guardia:6379/0") as got:
            assert got is client

    asyncio.run(_run())
    assert calls["url"] == "redis://guardia:6379/0"
    assert calls["kwargs"]["socket_connect_timeout"] == 1.0
    assert calls["kwargs"]["socket_timeout"] == 1.5
    assert "retry" in calls["kwargs"]
    assert client.closed is True


def test_cierra_tambien_si_el_cuerpo_lanza(fake):
    client, _ = fake

    async def _run():
        async with short_async_redis("redis://guardia:6379/0"):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(_run())
    assert client.closed is True


def test_las_guardas_usan_el_helper_sin_copias():
    root = Path(__file__).resolve().parents[1]
    for rel in ("app/core/rate_limit.py", "app/core/replay.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert "short_async_redis(redis_url)" in src, rel
        assert "redis.from_url(" not in src, rel
        assert "no_retry_async" not in src, rel
