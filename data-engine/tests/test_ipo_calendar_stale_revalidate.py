"""Stale-while-revalidate de la cache mensual de IPOs de NASDAQ.

Un mes bueno caducado (mas de 1 h, menos de 24 h) se sirve al momento y se
refresca en segundo plano; si el refresco falla se sigue sirviendo la copia.
Antes, cada hora, la primera carga de /calendar/ipos esperaba a NASDAQ.
"""

import asyncio
import time
from datetime import date

import pytest

from app.services.connectors import ipo_calendar as ipo

MONTH = date(2026, 10, 1)
OLD = {"status": "ok", "month": "2026-10", "events": [{"symbol": "OLD"}], "errors": []}
NEW_PAYLOAD = {
    "data": {
        "priced": {
            "rows": [{"proposedTickerSymbol": "NEW", "companyName": "New", "pricedDate": "10/02/2026"}]
        }
    }
}


@pytest.fixture(autouse=True)
def _clean():
    for name in ("_month_cache", "_month_refresh_failed"):
        getattr(ipo, name, {}).clear()
    yield
    for name in ("_month_cache", "_month_refresh_failed"):
        getattr(ipo, name, {}).clear()


def _expired() -> float:
    return time.monotonic() - ipo._MONTH_CACHE_TTL_S - 5  # noqa: SLF001


def test_expired_month_is_served_at_once_and_refreshed(monkeypatch):
    calls: list[str] = []

    async def run():
        release = asyncio.Event()

        async def slow(url, params, client):
            calls.append(params["date"])
            await release.wait()
            return NEW_PAYLOAD

        monkeypatch.setattr(ipo, "_get_json", slow)
        ipo._month_cache[MONTH] = (_expired(), OLD)  # noqa: SLF001
        first = await asyncio.wait_for(ipo.fetch_ipo_month(MONTH), 1.0)
        second = await asyncio.wait_for(ipo.fetch_ipo_month(MONTH), 1.0)
        assert first is OLD and second is OLD
        await asyncio.sleep(0)
        assert calls == ["2026-10"]
        release.set()
        for _ in range(5):
            await asyncio.sleep(0)
        fresh = await ipo.fetch_ipo_month(MONTH)
        assert fresh["status"] == "ok" and fresh is not OLD
        assert calls == ["2026-10"]

    asyncio.run(run())


def test_failed_refresh_keeps_the_good_copy(monkeypatch):
    calls: list[str] = []

    async def down(url, params, client):
        calls.append(params["date"])
        return None

    async def run():
        monkeypatch.setattr(ipo, "_get_json", down)
        ipo._month_cache[MONTH] = (_expired(), OLD)  # noqa: SLF001
        assert await ipo.fetch_ipo_month(MONTH) is OLD
        for _ in range(3):
            await asyncio.sleep(0)
        assert await ipo.fetch_ipo_month(MONTH) is OLD
        for _ in range(3):
            await asyncio.sleep(0)
        assert calls == ["2026-10"]  # sin reintento durante la cache negativa

    asyncio.run(run())


def test_month_older_than_a_day_waits_for_nasdaq(monkeypatch):
    async def down(url, params, client):
        return None

    monkeypatch.setattr(ipo, "_get_json", down)
    stale_max = getattr(ipo, "_MONTH_STALE_MAX_S", 86400.0)
    ipo._month_cache[MONTH] = (time.monotonic() - stale_max - 5, OLD)  # noqa: SLF001
    assert asyncio.run(ipo.fetch_ipo_month(MONTH))["status"] == "unavailable"
