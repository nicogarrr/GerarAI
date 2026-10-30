"""/calendar/ipos: cache por mes y tope de espera.

Antes cada carga pedía los dos meses a NASDAQ (~2 s) y, si NASDAQ colgaba,
esperaba el timeout de 20 s del cliente. Ahora un mes que responde se cachea
una hora, uno que falla un minuto, y ninguna espera pasa de RANGE_DEADLINE_S.
"""

import asyncio
from datetime import date

import pytest

from app.services.connectors import ipo_calendar as ipo

MONTHS = [date(2026, 10, 1), date(2026, 11, 1)]
PAYLOAD = {
    "data": {
        "priced": {
            "rows": [{"proposedTickerSymbol": "NEW", "companyName": "New Co", "pricedDate": "10/29/2026"}]
        }
    }
}


@pytest.fixture(autouse=True)
def _clean():
    getattr(ipo, "_month_cache", {}).clear()  # noqa: SLF001
    yield
    getattr(ipo, "_month_cache", {}).clear()  # noqa: SLF001


def test_second_load_does_not_call_nasdaq_again(monkeypatch):
    calls: list[str] = []

    async def fake_json(url, params, client):
        calls.append(params["date"])
        return PAYLOAD if params["date"] == "2026-10" else None

    monkeypatch.setattr(ipo, "_get_json", fake_json)
    first = asyncio.run(ipo.fetch_ipo_calendar(MONTHS))
    second = asyncio.run(ipo.fetch_ipo_calendar(MONTHS))
    assert calls == ["2026-10", "2026-11"]  # la segunda carga sale de la cache
    assert first == second and first["status"] == "partial"

    # El mes caído se reintenta pasado su TTL corto; el bueno sigue en cache.
    monkeypatch.setattr(ipo, "_MONTH_FAILURE_TTL_S", 0.0, raising=False)
    asyncio.run(ipo.fetch_ipo_calendar(MONTHS))
    assert calls == ["2026-10", "2026-11", "2026-11"]


def test_hanging_nasdaq_is_capped(monkeypatch):
    async def hang(url, params, client):
        await asyncio.sleep(5)
        return PAYLOAD

    monkeypatch.setattr(ipo, "_get_json", hang)
    monkeypatch.setattr(ipo, "RANGE_DEADLINE_S", 0.05, raising=False)
    result = asyncio.run(ipo.fetch_ipo_calendar(MONTHS[:1]))
    assert result["status"] == "unavailable"
    assert result["errors"] == ["2026-10: calendario de IPOs no disponible"]
