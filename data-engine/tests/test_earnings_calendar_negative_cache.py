"""Cache negativa breve del calendario NASDAQ (earnings/dividendos).

Con NASDAQ caido o lento, cada vista del calendario (calendario, catalizadores,
bloque del inicio) volvia a lanzar las consultas de todos los dias del rango y
a esperar hasta agotar el deadline. Ahora un dia que acaba de fallar se declara
«no disponible» al momento durante _DAY_FAILURE_TTL_S y despues se reintenta.
"""

import asyncio
import time
from datetime import date

import pytest

from app.services.connectors import earnings_calendar as ec

DAY = date(2026, 11, 2)


@pytest.fixture(autouse=True)
def _clean():
    ec._day_cache.clear()  # noqa: SLF001
    ec._day_failures.clear()  # noqa: SLF001
    yield
    ec._day_cache.clear()  # noqa: SLF001
    ec._day_failures.clear()  # noqa: SLF001


def test_failed_days_are_not_refetched_within_ttl(monkeypatch):
    calls: list[date] = []

    async def down(day, client):
        calls.append(day)
        await asyncio.sleep(0.2)  # NASDAQ lento que acaba fallando
        return None

    async def two_views():
        t0 = time.perf_counter()
        first = await ec._fetch_days(down, DAY, date(2026, 11, 4), None, kind="neg-test")  # noqa: SLF001
        t1 = time.perf_counter()
        second = await ec._fetch_days(down, DAY, date(2026, 11, 4), None, kind="neg-test")  # noqa: SLF001
        return first, second, t1 - t0, time.perf_counter() - t1

    first, second, first_s, second_s = asyncio.run(two_views())
    assert len(calls) == 3  # la segunda vista no vuelve a la red
    assert first == second == ([], [f"2026-11-0{d}: calendario no disponible" for d in (2, 3, 4)])
    assert first_s >= 0.2 and second_s < 0.05

    # Pasado el TTL se reintenta y un dia que vuelve se cachea como siempre.
    monkeypatch.setattr(ec, "_DAY_FAILURE_TTL_S", 0.0)

    async def up(day, client):
        calls.append(day)
        return [{"symbol": "AAPL", "date": day.isoformat()}]

    events, errors = asyncio.run(ec._fetch_days(up, DAY, DAY, None, kind="neg-test"))  # noqa: SLF001
    assert errors == [] and events == [{"symbol": "AAPL", "date": "2026-11-02"}]
    assert ("neg-test", DAY) not in ec._day_failures  # noqa: SLF001
