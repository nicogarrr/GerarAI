import asyncio
from datetime import date

from app.services.connectors import earnings_calendar as ec


def _reset():
    ec._day_cache.clear()
    ec._day_failures.clear()  # noqa: SLF001
    ec._day_inflight.clear()


def test_singleflight_dedupes_in_same_loop():
    _reset()
    calls = []

    async def fetch_day(day, client):
        calls.append(day)
        await asyncio.sleep(0.01)
        return [{"d": str(day)}]

    async def run():
        day = date(2026, 10, 19)
        return await asyncio.gather(
            ec._fetch_day_pooled("earnings", day, fetch_day, None),
            ec._fetch_day_pooled("earnings", day, fetch_day, None),
        )

    a, b = asyncio.run(run())
    assert a == b
    assert len(calls) == 1


def test_singleflight_two_loops_same_day_no_cross_loop_error():
    _reset()

    async def fetch_day(day, client):
        return [{"d": str(day)}]

    day = date(2026, 10, 20)
    first = asyncio.run(ec._fetch_day_pooled("earnings", day, fetch_day, None))
    ec._day_cache.clear()
    ec._day_failures.clear()  # noqa: SLF001
    second = asyncio.run(ec._fetch_day_pooled("earnings", day, fetch_day, None))
    assert first == second == [{"d": str(day)}]
