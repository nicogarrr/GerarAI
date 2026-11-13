"""Missing source calendars are not evidence that there are no events."""
import asyncio
from datetime import date

import pytest

from app.services.connectors import earnings_calendar as ec


@pytest.mark.parametrize('kind', ['earnings', 'dividends'])
@pytest.mark.parametrize('payload', [{'data': None}, {'message': 'unavailable'}, {'data': {}}, {'data': {'calendar': {}}}])
def test_missing_source_calendar_degrades_instead_of_empty_ok(monkeypatch, kind, payload):
    async def fake(*_):
        return payload
    monkeypatch.setattr(ec, '_get_json', fake)
    day = date(2026, 11, 13)
    result = asyncio.run(getattr(ec, f'fetch_{kind}_range')(day, day, client=object()))
    assert result['status'] == 'unavailable'
    assert result['events'] == []
    assert result['errors']


@pytest.mark.parametrize('kind', ['earnings', 'dividends'])
@pytest.mark.parametrize('rows', [None, []])
def test_explicit_empty_rows_are_still_verified_empty(monkeypatch, kind, rows):
    async def fake(*_):
        table = {'rows': rows}
        return {'data': {'calendar': table} if kind == 'dividends' else table}
    monkeypatch.setattr(ec, '_get_json', fake)
    day = date(2026, 11, 13)
    result = asyncio.run(getattr(ec, f'fetch_{kind}_range')(day, day, client=object()))
    assert result['status'] == 'ok'
    assert result['events'] == [] and result['errors'] == []
