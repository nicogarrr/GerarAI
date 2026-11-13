"""Un mismo deal entre meses sigue siendo una sola salida a bolsa."""
import asyncio
from datetime import date

import pytest

from app.services.connectors import ipo_calendar as ipo


def _event(deal, status, day):
    return {'deal_id': deal, 'symbol': 'ABC', 'company': 'Example', 'date': day, 'status': status}


@pytest.mark.parametrize('priced_month', [10, 11])
def test_same_deal_across_months_prefers_priced(monkeypatch, priced_month):
    async def month(first, client=None):
        priced = first.month == priced_month
        return {'status': 'ok', 'month': first.strftime('%Y-%m'), 'errors': [], 'events': [
            _event('deal-1', 'priced' if priced else 'upcoming',
                   '2026-10-30' if priced else '2026-11-02')
        ]}
    monkeypatch.setattr(ipo, 'fetch_ipo_month', month)
    result = asyncio.run(ipo.fetch_ipo_calendar([date(2026, 10, 1), date(2026, 11, 1)]))
    assert result['count'] == 1
    assert result['events'][0]['status'] == 'priced'
    assert result['events'][0]['date'] == '2026-10-30'
    assert result['status'] == 'ok'


def test_distinct_deals_and_unidentified_dates_survive(monkeypatch):
    async def month(first, client=None):
        return {'status': 'ok', 'month': first.strftime('%Y-%m'), 'errors': [], 'events': [
            _event(f'deal-{first.month}', 'upcoming', '2026-11-02'),
            _event(None, 'upcoming', first.isoformat()),
        ]}
    monkeypatch.setattr(ipo, 'fetch_ipo_month', month)
    result = asyncio.run(ipo.fetch_ipo_calendar([date(2026, 10, 1), date(2026, 11, 1)]))
    assert result['count'] == 4


def test_legacy_event_without_status_or_deal_id_is_preserved():
    legacy = {'symbol': 'ABC', 'company': 'Example', 'date': '2026-11-02'}
    assert ipo._unique_deals([legacy]) == [legacy]


def test_unknown_status_does_not_replace_known_priced_record():
    legacy = _event('deal-1', 'upcoming', '2026-11-02')
    legacy.pop('status')
    priced = _event('deal-1', 'priced', '2026-10-30')
    assert ipo._unique_deals([legacy, priced]) == [priced]
