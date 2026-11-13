"""Aged earnings/dividend caches are not presented as fresh source responses."""
import asyncio
import time
from datetime import date

import pytest

from app.services.connectors import earnings_calendar as ec


@pytest.mark.parametrize('kind', ['earnings', 'dividends'])
@pytest.mark.parametrize('rows', [[], [{'symbol': 'ABC', 'date': '2026-11-02'}]])
def test_stale_days_are_partial_even_when_the_cached_day_has_no_events(monkeypatch, kind, rows):
    day = date(2026, 11, 2)
    stored_at = time.monotonic() - ec._DAY_CACHE_TTL_S - 5
    monkeypatch.setattr(ec, '_day_cache', {(kind, day): (stored_at, rows)})
    monkeypatch.setattr(ec, '_day_failures', {(kind, day): time.monotonic()})
    result = asyncio.run(getattr(ec, f'fetch_{kind}_range')(day, day))
    assert result['status'] == 'partial'
    assert result['events'] == rows
    assert result['stale_days'] == [day.isoformat()]
    assert 'copia' in result['errors'][0]
    assert ec._day_cache[(kind, day)] == (stored_at, rows)
