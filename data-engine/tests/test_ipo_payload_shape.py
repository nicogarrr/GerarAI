"""A JSON envelope without an IPO calendar is not proof of zero events."""
import asyncio
from datetime import date

import pytest

from app.services.connectors import ipo_calendar as ipo


@pytest.mark.parametrize('payload', [
    {'data': None}, {'message': 'not available'}, {'data': {}},
    {'data': {'unexpectedTable': {'rows': []}}},
])
def test_missing_ipo_calendar_is_unavailable_not_empty(monkeypatch, payload):
    async def fake(*_):
        return payload
    monkeypatch.setattr(ipo, '_get_json', fake)
    result = asyncio.run(ipo.fetch_ipo_month(date(2026, 11, 1), client=object()))
    assert result['status'] == 'unavailable'
    assert result['errors']
    assert result['events'] == []


def test_explicit_empty_calendar_remains_ok(monkeypatch):
    async def fake(*_):
        return {'data': {'priced': {'rows': None}, 'upcoming': {'upcomingTable': {'rows': None}}}}
    monkeypatch.setattr(ipo, '_get_json', fake)
    result = asyncio.run(ipo.fetch_ipo_month(date(2026, 11, 1), client=object()))
    assert result['status'] == 'ok'
    assert result['events'] == []
    assert result['errors'] == []
