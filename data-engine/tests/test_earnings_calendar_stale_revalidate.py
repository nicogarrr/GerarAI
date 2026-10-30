"""Stale-while-revalidate del calendario NASDAQ por dia.

Cada hora caducaba la cache de dias y la primera vista del calendario o de los
catalizadores volvia a esperar a NASDAQ (~3 s por dia, hasta el deadline de
8 s del rango). Ahora un dia caducado de menos de 24 h se sirve al momento y
se refresca en segundo plano; si el refresco falla se sigue sirviendo.
"""

import asyncio
import time
from datetime import date

import pytest

from app.services.connectors import earnings_calendar as ec

DAY = date(2026, 11, 2)
KEY = ("swr-test", DAY)
OLD = [{"symbol": "OLD"}]
NEW = [{"symbol": "NEW"}]


@pytest.fixture(autouse=True)
def _clean():
    ec._day_cache.clear()  # noqa: SLF001
    ec._day_failures.clear()  # noqa: SLF001
    yield
    ec._day_cache.clear()  # noqa: SLF001
    ec._day_failures.clear()  # noqa: SLF001


def _age(seconds: float) -> float:
    return time.monotonic() - seconds


def test_expired_day_is_served_at_once_and_refreshed_in_background():
    async def run():
        release = asyncio.Event()
        calls: list[date] = []

        async def slow(day, client):
            calls.append(day)
            await release.wait()
            return NEW

        ec._day_cache[KEY] = (_age(ec._DAY_CACHE_TTL_S + 5), OLD)  # noqa: SLF001
        first = await asyncio.wait_for(ec._fetch_day_pooled("swr-test", DAY, slow, None), 1.0)  # noqa: SLF001
        second = await asyncio.wait_for(ec._fetch_day_pooled("swr-test", DAY, slow, None), 1.0)  # noqa: SLF001
        assert first == OLD and second == OLD
        await asyncio.sleep(0)
        assert calls == [DAY]  # un solo refresco en vuelo
        release.set()
        for _ in range(5):
            await asyncio.sleep(0)
        assert ec._day_cache[KEY][1] == NEW  # noqa: SLF001
        assert await ec._fetch_day_pooled("swr-test", DAY, slow, None) == NEW  # noqa: SLF001
        assert calls == [DAY]

    asyncio.run(run())


def test_failed_refresh_keeps_serving_the_copy():
    async def run():
        calls: list[date] = []

        async def down(day, client):
            calls.append(day)
            return None

        ec._day_cache[KEY] = (_age(ec._DAY_CACHE_TTL_S + 5), OLD)  # noqa: SLF001
        assert await ec._fetch_day_pooled("swr-test", DAY, down, None) == OLD  # noqa: SLF001
        for _ in range(3):
            await asyncio.sleep(0)
        assert await ec._fetch_day_pooled("swr-test", DAY, down, None) == OLD  # noqa: SLF001
        for _ in range(3):
            await asyncio.sleep(0)
        assert calls == [DAY]  # la cache negativa frena los reintentos

    asyncio.run(run())


def test_copy_older_than_a_day_is_not_served():
    async def run():
        async def fresh(day, client):
            return NEW

        ec._day_cache[KEY] = (_age(getattr(ec, "_DAY_STALE_MAX_S", 86400.0) + 5), OLD)  # noqa: SLF001
        assert await ec._fetch_day_pooled("swr-test", DAY, fresh, None) == NEW  # noqa: SLF001

    asyncio.run(run())
