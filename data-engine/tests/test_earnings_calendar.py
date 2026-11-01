"""Tests hermeticos del calendario NASDAQ (red mockeada con httpx.MockTransport).

Run from data-engine/:
    pytest tests/test_earnings_calendar.py -v
"""

import asyncio
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.services.connectors import earnings_calendar as connector

NASDAQ_EARNINGS_PAYLOAD = {
    "data": {
        "asOf": "Thu, Sep 17, 2026",
        "headers": {"symbol": "Symbol", "name": "Company Name"},
        "rows": [
            {
                "symbol": "ACN",
                "name": "Accenture plc",
                "time": "before-market",
                "epsForecast": "2.95",
                "noOfEsts": "14",
                "fiscalQuarterEnding": "8/31/2026",
                "marketCap": "220,000,000,000",
            },
            {"symbol": "", "name": "Sin simbolo: se filtra"},
        ],
    }
}

NASDAQ_DIVIDENDS_PAYLOAD = {
    "data": {
        "calendar": {
            "asOf": "Thu, Sep 17, 2026",
            "rows": [
                {
                    "symbol": "KO",
                    "companyName": "Coca-Cola",
                    "dividend_Ex_Date": "2026-09-18",
                    "payment_Date": "2026-10-01",
                    "record_Date": "2026-09-19",
                    "dividend_Rate": "0.51",
                }
            ],
        }
    }
}


def run_async(coroutine):
    return asyncio.run(coroutine)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_fetch_earnings_day_normalizes_rows():
    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "date" in request.url.params
            assert "Mozilla" in request.headers["user-agent"]
            return httpx.Response(200, json=NASDAQ_EARNINGS_PAYLOAD, request=request)

        async with _client(handler) as client:
            return await connector.fetch_earnings_day(date(2026, 9, 17), client)

    events = run_async(probe())
    assert len(events) == 1  # la fila sin simbolo se filtra
    assert events[0]["symbol"] == "ACN"
    assert events[0]["date"] == "2026-09-17"
    assert events[0]["eps_forecast"] == pytest.approx(2.95)
    assert events[0]["n_estimates"] == pytest.approx(14.0)
    assert events[0]["market_cap"] == pytest.approx(220_000_000_000.0)


def test_fetch_earnings_day_degrades_to_none_on_failure():
    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="caido", request=request)

        async with _client(handler) as client:
            return await connector.fetch_earnings_day(date(2026, 9, 17), client)

    assert run_async(probe()) is None


def test_fetch_earnings_day_degrades_to_none_on_connection_error():
    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("red caida")

        async with _client(handler) as client:
            return await connector.fetch_earnings_day(date(2026, 9, 17), client)

    assert run_async(probe()) is None


def test_fetch_range_aggregates_and_marks_partial():
    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.params["date"] == "2026-09-17":
                return httpx.Response(200, json=NASDAQ_EARNINGS_PAYLOAD, request=request)
            return httpx.Response(500, text="caido", request=request)

        async with _client(handler) as client:
            return await connector.fetch_earnings_range(
                date(2026, 9, 17), date(2026, 9, 18), client
            )

    result = run_async(probe())
    assert result["status"] == "partial"
    assert result["count"] == 1
    assert len(result["errors"]) == 1
    assert "2026-09-18" in result["errors"][0]


def test_fetch_range_unavailable_when_everything_fails():
    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("red caida")

        async with _client(handler) as client:
            return await connector.fetch_earnings_range(
                date(2026, 9, 17), date(2026, 9, 17), client
            )

    result = run_async(probe())
    assert result["status"] == "unavailable"
    assert result["events"] == []


def test_fetch_range_rejects_bad_ranges():
    with pytest.raises(ValueError, match="posterior"):
        run_async(connector.fetch_earnings_range(date(2026, 9, 18), date(2026, 9, 17)))
    with pytest.raises(ValueError, match="máximo"):
        run_async(connector.fetch_earnings_range(date(2026, 1, 1), date(2026, 3, 15)))


def test_fetch_dividends_day_normalizes_rows():
    async def probe():
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=NASDAQ_DIVIDENDS_PAYLOAD, request=request)

        async with _client(handler) as client:
            return await connector.fetch_dividends_day(date(2026, 9, 17), client)

    events = run_async(probe())
    assert len(events) == 1
    assert events[0]["symbol"] == "KO"
    assert events[0]["amount"] == pytest.approx(0.51)
    assert events[0]["ex_date"] == "2026-09-18"


def test_calendar_earnings_route_serves_connector(monkeypatch):
    import main

    async def fake_range(desde, hasta, client=None):
        return {
            "status": "ok",
            "desde": desde.isoformat(),
            "hasta": hasta.isoformat(),
            "count": 1,
            "events": [{"symbol": "ACN"}],
            "errors": [],
        }

    monkeypatch.setattr(connector, "fetch_earnings_range", fake_range)
    client = TestClient(main.app, raise_server_exceptions=False)
    response = client.get("/api/calendar/earnings?desde=2026-09-17&hasta=2026-09-18")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 1
    assert payload["events"][0]["symbol"] == "ACN"


def test_calendar_earnings_route_rejects_inverted_range(monkeypatch):
    import main

    async def boom(*args, **kwargs):  # pragma: no cover — no debe llamarse
        raise AssertionError("el conector no debe llamarse con rango invalido")

    monkeypatch.setattr(connector, "fetch_earnings_range", boom)
    client = TestClient(main.app, raise_server_exceptions=False)
    response = client.get("/api/calendar/earnings?desde=2026-09-18&hasta=2026-09-17")
    assert response.status_code == 400


def test_fetch_range_no_es_secuencial_y_conserva_errores(monkeypatch):
    """NASDAQ tarda ~2.4s por dia: 7 dias en serie = ~17s por peticion
    (observado en prod: "slow request 17.1s"). El rango debe consultar los
    dias en paralelo acotado, manteniendo el orden por dia y los errores
    por dia."""
    import asyncio
    import time

    from app.services.connectors import earnings_calendar as cal

    days_queried: list[str] = []
    in_flight = 0
    max_in_flight = 0

    async def fake_day(day, client=None):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        days_queried.append(day.isoformat())
        if day.day % 2 == 0:
            return None  # este dia falla
        return [{"symbol": f"T{day.day}", "date": day.isoformat()}]

    monkeypatch.setattr(cal, "fetch_earnings_day", fake_day)
    start = date(2026, 10, 1)
    end = date(2026, 10, 10)  # 10 dias

    t0 = time.monotonic()
    result = asyncio.run(cal.fetch_earnings_range(start, end))
    elapsed = time.monotonic() - t0

    assert elapsed < 0.45, f"10 dias en {elapsed:.2f}s: sigue siendo secuencial"
    assert max_in_flight >= 2, "no hubo concurrencia real"
    # orden por dia conservado en eventos y errores, semantica intacta
    assert result["status"] == "partial"
    assert [e["date"] for e in result["events"]] == [
        f"2026-10-{d:02d}" for d in range(1, 11) if d % 2 == 1
    ]
    assert result["errors"] == [
        f"2026-10-{d:02d}: calendario no disponible" for d in range(1, 11) if d % 2 == 0
    ]
