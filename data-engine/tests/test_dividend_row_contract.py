"""Explicit malformed dividend rows are not an observed empty calendar."""
import asyncio
from datetime import date

import pytest

from app.services.connectors import earnings_calendar as ec


@pytest.mark.parametrize('rows', [{}, '', False, [None], ['invalid']])
def test_malformed_dividend_rows_degrade(monkeypatch, rows):
    async def fake(*args):
        return {'data': {'calendar': {'rows': rows}}}
    monkeypatch.setattr(ec, '_get_json', fake)
    day = date(2026, 11, 13)
    result = asyncio.run(ec.fetch_dividends_range(day, day, client=object()))
    assert result['status'] == 'unavailable'
    assert result['events'] == []
    assert result['errors']


@pytest.mark.parametrize('rows', [None, []])
def test_explicit_empty_dividend_rows_stay_verified(monkeypatch, rows):
    async def fake(*args):
        return {'data': {'calendar': {'rows': rows}}}
    monkeypatch.setattr(ec, '_get_json', fake)
    day = date(2026, 11, 13)
    result = asyncio.run(ec.fetch_dividends_range(day, day, client=object()))
    assert result['status'] == 'ok'
    assert result['events'] == []
