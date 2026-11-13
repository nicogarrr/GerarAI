"""A section object alone does not prove an observed empty IPO calendar."""
import asyncio
from datetime import date

import pytest

from app.services.connectors import ipo_calendar as ipo


@pytest.mark.parametrize('data', [
    {'priced': {}}, {'upcoming': {}}, {'upcoming': {'upcomingTable': {}}},
    {'priced': {'rows': {}}}, {'priced': {'rows': ''}},
    {'priced': {'rows': [None]}}, {'priced': {'rows': ['invalid']}},
    {'priced': {'rows': []}, 'upcoming': {'upcomingTable': {'rows': [None]}}},
])
def test_unverified_rows_do_not_become_empty_or_partial_success(monkeypatch, data):
    async def fake(*args):
        return {'data': data}
    monkeypatch.setattr(ipo, '_get_json', fake)
    result = asyncio.run(ipo.fetch_ipo_month(date(2026, 11, 1), client=object()))
    assert result['status'] == 'unavailable'
    assert result['errors']


@pytest.mark.parametrize('rows', [None, []])
def test_explicit_empty_rows_still_mean_observed_empty(monkeypatch, rows):
    async def fake(*args):
        return {'data': {'priced': {'rows': rows}}}
    monkeypatch.setattr(ipo, '_get_json', fake)
    result = asyncio.run(ipo.fetch_ipo_month(date(2026, 11, 1), client=object()))
    assert result['status'] == 'ok'
    assert result['events'] == []
