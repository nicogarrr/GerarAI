"""Hermetic tests: Stooq daily CSV fallback. No network."""

import asyncio
from datetime import date

import httpx
import pytest

from app.services.connectors.stooq import StooqClient


def _run(handler, symbol, start, end):
    async def _go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await StooqClient(client).daily_prices(symbol, start=start, end=end)

    return asyncio.run(_go())


def test_stooq_parses_daily_csv_with_source_and_date():
    def handler(request):
        assert request.url.params["s"] == "aapl.us"
        return httpx.Response(200, text="Date,Open,High,Low,Close,Volume\n2026-09-24,100.1,103,99,102.5,1234\n")

    rows = _run(handler, "AAPL.US", date(2026, 9, 1), date(2026, 9, 25))
    assert rows[0]["date"] == date(2026, 9, 24)
    assert str(rows[0]["close"]) == "102.5"
    assert rows[0]["volume"] == 1234
    assert rows[0]["source"] == "stooq"


def test_stooq_rejects_challenge_and_bad_prices():
    with pytest.raises(RuntimeError, match="HTML"):
        _run(lambda _: httpx.Response(200, text="<!DOCTYPE html><html>verify browser</html>"),
             "aapl.us", date(2026, 9, 1), date(2026, 9, 25))
    with pytest.raises(RuntimeError, match="invalid"):
        _run(lambda _: httpx.Response(200, text="Date,Open,High,Low,Close,Volume\n2026-09-24,100,103,99,-1,10\n"),
             "aapl.us", date(2026, 9, 1), date(2026, 9, 25))


def test_basic_fit_yahoo_symbol_maps_to_verified_stooq_listing():
    def handler(request):
        assert request.url.params["s"] == "bfit.nl"
        return httpx.Response(200, text="Date,Open,High,Low,Close,Volume\n2026-09-24,30,31,29,30,100\n")

    rows = _run(handler, "BFIT.AS", date(2026, 9, 1), date(2026, 9, 25))
    assert rows[0]["symbol"] == "bfit.nl"
