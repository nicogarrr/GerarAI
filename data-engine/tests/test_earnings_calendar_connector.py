"""Contratos del conector earnings_calendar (NASDAQ): parseo de importes
(negativos entre parentesis, centinelas N/A), normalizacion de filas,
degradacion por dia (fallo -> None y registry, nunca 5xx) y cache por dia
con singleflight y cache negativa.

La cache es estado de proceso: los tests que la usan la limpian antes y
despues (fixture), y la red es siempre un MockTransport o una bomba.
"""

import asyncio
import time
from datetime import date

import httpx
import pytest

from app.services.connectors import earnings_calendar as ec
from app.services.data_source_health import get_data_source_registry


def run_async(coroutine):
    return asyncio.run(coroutine)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _clean_day_state():
    ec._day_cache.clear()
    ec._day_failures.clear()
    ec._day_inflight.clear()
    yield
    ec._day_cache.clear()
    ec._day_failures.clear()
    ec._day_inflight.clear()


def _nasdaq_failures() -> int:
    return get_data_source_registry().get_status("nasdaq").consecutive_failures


# -- parseo y normalizacion ---------------------------------------------------


def test_parse_float_centinelas_y_parentesis():
    for sentinel in (None, "", "--", "N/A", "time-not-supplied"):
        assert ec._parse_float(sentinel) is None
    assert ec._parse_float("($0.05)") == -0.05      # NASDAQ: negativos entre parentesis
    assert ec._parse_float("$1,234.5") == 1234.5
    assert ec._parse_float("no-numero") is None


def test_normalize_earnings_row():
    row = {
        "symbol": "aapl", "name": "Apple Inc.", "time": "time-after-hours",
        "epsForecast": "$1.25", "noOfEsts": "12", "fiscalQuarterEnding": "Sep/2025",
        "marketCap": "$3,000,000,000",
    }
    out = ec.normalize_earnings_row(row, date(2025, 10, 30))
    assert out["symbol"] == "AAPL"
    assert out["eps_forecast"] == 1.25
    assert out["n_estimates"] == 12
    assert out["market_cap"] == 3000000000.0
    assert out["date"] == "2025-10-30"
    # centinela "--" -> None
    out2 = ec.normalize_earnings_row({"symbol": "X", "epsForecast": "--"}, date(2025, 10, 30))
    assert out2["eps_forecast"] is None


def test_normalize_dividend_row_fallbacks():
    row = {
        "symbol": "ko", "companyName": "Coca-Cola", "dividend_Ex_Date": "2025-11-28",
        "payment_Date": "2025-12-15", "record_Date": "2025-11-28", "dividend_Rate": "0.485",
    }
    out = ec.normalize_dividend_row(row, date(2025, 11, 28))
    assert out["symbol"] == "KO" and out["company"] == "Coca-Cola" and out["amount"] == 0.485
    # fallbacks: name si no hay companyName; amount si no hay dividend_Rate
    row2 = {"symbol": "X", "name": "X Corp", "amount": "1.5"}
    out2 = ec.normalize_dividend_row(row2, date(2025, 11, 28))
    assert out2["company"] == "X Corp" and out2["amount"] == 1.5


def test_check_range_invertido_y_demasiado_largo():
    with pytest.raises(ValueError, match="posterior"):
        ec._check_range(date(2025, 2, 10), date(2025, 2, 1))
    with pytest.raises(ValueError, match="máximo"):
        ec._check_range(date(2025, 1, 1), date(2025, 3, 1))


# -- degradacion por dia --------------------------------------------------------


def test_get_json_error_http_es_none_y_registra():
    before = _nasdaq_failures()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    async def probe():
        async with _client(handler) as client:
            return await ec.fetch_earnings_day(date(2025, 10, 30), client)

    assert run_async(probe()) is None
    assert _nasdaq_failures() == before + 1


def test_get_json_payload_no_dict_es_none_y_registra():
    before = _nasdaq_failures()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["no", "dict"], request=request)

    async def probe():
        async with _client(handler) as client:
            return await ec.fetch_earnings_day(date(2025, 10, 30), client)

    assert run_async(probe()) is None
    assert _nasdaq_failures() == before + 1


def test_fetch_earnings_day_filtra_filas_sin_symbol():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"rows": [
            {"symbol": "AAPL", "name": "Apple"},
            {"name": "Sin simbolo"},
        ]}}, request=request)

    async def probe():
        async with _client(handler) as client:
            return await ec.fetch_earnings_day(date(2025, 10, 30), client)

    events = run_async(probe())
    assert len(events) == 1 and events[0]["symbol"] == "AAPL"


def test_fetch_dividends_day_calendar_anidado_y_plano():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"calendar": {"rows": [
            {"symbol": "KO", "dividend_Rate": "0.485"},
        ]}}}, request=request)

    async def probe():
        async with _client(handler) as client:
            return await ec.fetch_dividends_day(date(2025, 11, 28), client)

    events = run_async(probe())
    assert len(events) == 1 and events[0]["symbol"] == "KO"


# -- rango: status de degradacion -----------------------------------------------


def test_fetch_earnings_range_unavailable_si_todos_fallan():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    async def probe():
        async with _client(handler) as client:
            return await ec.fetch_earnings_range(date(2025, 10, 30), date(2025, 10, 31), client)

    out = run_async(probe())
    assert out["status"] == "unavailable"
    assert out["events"] == [] and len(out["errors"]) == 2


def test_fetch_earnings_range_partial_si_falla_un_dia():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["date"] == "2025-10-30":
            return httpx.Response(200, json={"data": {"rows": [{"symbol": "AAPL"}]}}, request=request)
        return httpx.Response(500, request=request)

    async def probe():
        async with _client(handler) as client:
            return await ec.fetch_earnings_range(date(2025, 10, 30), date(2025, 10, 31), client)

    out = run_async(probe())
    assert out["status"] == "partial"
    assert out["count"] == 1 and len(out["errors"]) == 1


def test_fetch_earnings_range_ok_sin_errores():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"rows": [{"symbol": "AAPL"}]}}, request=request)

    async def probe():
        async with _client(handler) as client:
            return await ec.fetch_earnings_range(date(2025, 10, 30), date(2025, 10, 30), client)

    out = run_async(probe())
    assert out["status"] == "ok" and out["count"] == 1 and out["errors"] == []


# -- cache por dia (camino de produccion, sin cliente inyectado) ----------------


def _no_network(monkeypatch):
    def boom():
        raise AssertionError("no debe haber red: la cache debia resolver")

    monkeypatch.setattr(ec, "_pooled_client", boom)


def test_cache_hit_reciente_no_usa_la_red(monkeypatch):
    _no_network(monkeypatch)
    day = date(2025, 10, 30)
    ec._day_cache[("earnings", day)] = (time.monotonic(), [{"symbol": "AAPL"}])
    out = run_async(ec.fetch_earnings_range(day, day, None))
    assert out["status"] == "ok" and out["events"] == [{"symbol": "AAPL"}]


def test_cache_negativa_reciente_es_unavailable_sin_red(monkeypatch):
    _no_network(monkeypatch)
    day = date(2025, 10, 30)
    ec._day_failures[("earnings", day)] = time.monotonic()
    out = run_async(ec.fetch_earnings_range(day, day, None))
    assert out["status"] == "unavailable"


def test_stale_while_revalidate_sirve_copia_y_refresca(monkeypatch):
    day = date(2025, 10, 30)
    stale_events = [{"symbol": "VIEJO"}]
    ec._day_cache[("earnings", day)] = (time.monotonic() - ec._DAY_CACHE_TTL_S - 10, stale_events)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"rows": [{"symbol": "NUEVO"}]}}, request=request)

    pooled = _client(handler)
    monkeypatch.setattr(ec, "_pooled_client", lambda: pooled)

    async def probe():
        out = await ec.fetch_earnings_range(day, day, None)
        # la respuesta inmediata es la copia stale; el refresco va en segundo plano
        await asyncio.sleep(0.2)
        return out

    out = run_async(probe())
    assert out["events"] == stale_events
    stored = ec._day_cache[("earnings", day)][1]
    assert [e["symbol"] for e in stored] == ["NUEVO"]  # refresco guardado (evento normalizado)
    run_async(pooled.aclose())
