"""Hermetic Stooq boundary and health contracts, without real provider access."""

import asyncio
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import httpx
import pytest

from app.services.connectors import stooq

START, END = date(2026, 1, 1), date(2026, 1, 31)
HEADER = "Date,Open,High,Low,Close,Volume\n"


@pytest.fixture
def health(monkeypatch):
    registry = Mock()
    monkeypatch.setattr(stooq, "get_data_source_registry", lambda: registry)
    return registry


def run_response(text, *, status=200):
    async def go():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(status, text=text))
        ) as client:
            return await stooq.StooqClient(client).daily_prices("aapl.us", start=START, end=END)

    return asyncio.run(go())


@pytest.mark.parametrize(
    "symbol,start,end",
    [
        ("aapl.us", END, START),
        ("", START, END),
        ("  ", START, END),
        ("aapl/us", START, END),
        ("áapl", START, END),
    ],
)
def test_invalid_inputs_do_not_request_or_touch_health(symbol, start, end, health):
    client = Mock()
    with pytest.raises(ValueError):
        asyncio.run(stooq.StooqClient(client).daily_prices(symbol, start=start, end=end))
    client.get.assert_not_called()
    assert health.mock_calls == []


@pytest.mark.parametrize("status", [400, 404])
def test_symbol_errors_raise_without_changing_health(status, health):
    with pytest.raises(httpx.HTTPStatusError) as exc:
        run_response("unknown", status=status)
    assert exc.value.response.status_code == status
    assert health.mock_calls == []


def test_transport_error_preserves_exception_and_records_failure(health):
    error = httpx.ReadTimeout("timed out")

    def handler(_):
        raise error

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await stooq.StooqClient(client).daily_prices("aapl.us", start=START, end=END)

    with pytest.raises(httpx.ReadTimeout) as exc:
        asyncio.run(go())
    assert exc.value is error
    health.record_failure.assert_called_once_with("stooq", "error de red: ReadTimeout")
    health.record_success.assert_not_called()


@pytest.mark.parametrize("text", ["", "Date,Close\n2026-01-03,12", "date,Open,High,Low,Close,Volume"])
def test_unexpected_csv_schema_is_not_success(text, health):
    with pytest.raises(RuntimeError, match="unexpected CSV schema"):
        run_response(text)
    health.record_failure.assert_called_once_with("stooq", "esquema CSV inesperado")
    health.record_success.assert_not_called()


@pytest.mark.parametrize(
    "row",
    [
        "2026-02-01,1,2,1,2,10",
        "2025-12-31,1,2,1,2,10",
        "2026-01-10,1,2,1,Infinity,10",
        "2026-01-10,1,2,1,NaN,10",
        "2026-01-10,1,2,1,no-price,10",
        "not-a-date,1,2,1,2,10",
        "2026-01-10,1,2,1,0,10",
        "2026-01-10,1,2,1,2,-1",
        "2026-01-10,1,2,1,2,1.5",
        "2026-01-10,1,2,1,2",
        "2026-01-10,1,2",
    ],
)
def test_invalid_rows_fail_closed_without_partial_prices(row, health):
    with pytest.raises(RuntimeError, match="invalid OHLCV row") as exc:
        run_response(HEADER + "2026-01-01,1,2,1,2,0\n" + row + "\n")
    assert exc.value.__cause__ is not None
    health.record_failure.assert_called_once_with("stooq", "fila OHLCV invalida")
    health.record_success.assert_not_called()


@pytest.mark.parametrize("text", [" \n No DATA for symbol \n", HEADER])
def test_valid_empty_responses_record_success(text, health):
    assert run_response(text) == []
    health.record_failure.assert_not_called()
    health.record_success.assert_called_once()
    key, elapsed = health.record_success.call_args.args
    assert key == "stooq" and elapsed >= 0


def test_owned_client_options_query_and_inclusive_dates(monkeypatch, health):
    original_client = httpx.AsyncClient
    options = []

    def handler(request):
        assert request.url.host == "stooq.com"
        assert request.url.path == "/q/d/l/"
        assert dict(request.url.params) == {"s": "aapl.us", "i": "d", "d1": "20260101", "d2": "20260131"}
        return httpx.Response(200, text=HEADER + "2026-01-01,1.01,2,1,1.5,0\n2026-01-31,2,3,1,2.5,9\n")

    def factory(**kwargs):
        options.append(kwargs)
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(stooq.httpx, "AsyncClient", factory)
    client = stooq.StooqClient()
    assert client.configured() is True
    rows = asyncio.run(client.daily_prices(" AAPL.US ", start=START, end=END))
    assert options == [{"timeout": 20, "follow_redirects": True}]
    assert [r["date"] for r in rows] == [START, END]
    assert rows[0]["open"] == Decimal("1.01")
    assert rows[0]["high"] == Decimal("2")
    assert rows[0]["low"] == Decimal("1")
    assert rows[0]["close"] == Decimal("1.5")
    assert [r["volume"] for r in rows] == [0, 9]
    assert all(r["source"] == "stooq" and r["symbol"] == "aapl.us" for r in rows)
    assert rows[0]["source_url"] == "https://stooq.com/q/d/l/?s=aapl.us&i=d&d1=20260101&d2=20260131"
    health.record_failure.assert_not_called()
    health.record_success.assert_called_once()
