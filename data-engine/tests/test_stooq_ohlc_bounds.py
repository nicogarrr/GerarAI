"""A positive number alone does not make a coherent daily OHLC bar."""

import asyncio
from datetime import date
from unittest.mock import Mock

import httpx
import pytest

from app.services.connectors import stooq

HEADER = "Date,Open,High,Low,Close,Volume\n"


def run_bar(prices):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=HEADER + f"2026-01-02,{prices},100\n")
        )) as client:
            return await stooq.StooqClient(client).daily_prices(
                "aapl.us", start=date(2026, 1, 1), end=date(2026, 1, 31)
            )
    return asyncio.run(go())


@pytest.mark.parametrize("prices", [
    "100,90,110,100",  # high below low
    "120,110,90,100",  # open above high
    "80,110,90,100",  # open below low
    "100,110,90,120",  # close above high
    "100,110,90,80",  # close below low
])
def test_incoherent_bar_is_not_a_success(prices, monkeypatch):
    health = Mock()
    monkeypatch.setattr(stooq, "get_data_source_registry", lambda: health)
    with pytest.raises(RuntimeError, match="invalid OHLCV row"):
        run_bar(prices)
    health.record_failure.assert_called_once_with("stooq", "fila OHLCV invalida")
    health.record_success.assert_not_called()


@pytest.mark.parametrize("prices", ["100,100,100,100", "90,110,90,110", "110,110,90,90"])
def test_bounds_are_inclusive_and_flat_sessions_remain_valid(prices):
    assert len(run_bar(prices)) == 1
