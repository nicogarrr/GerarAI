"""Stale IPO copies remain usable but never silently look refreshed."""
import asyncio
import time
from datetime import date

from app.services.connectors import ipo_calendar as ipo


def test_stale_month_reaches_calendar_as_partial_without_losing_events(monkeypatch):
    month = date(2026, 11, 1)
    old = {'status': 'ok', 'month': '2026-11', 'errors': [],
           'events': [{'symbol': 'ABC', 'date': '2026-11-20', 'company': 'ABC'}]}
    monkeypatch.setattr(ipo, '_month_cache', {month: (time.monotonic() - 7200, old)})
    monkeypatch.setattr(ipo, '_refresh_month', lambda _: None)
    result = asyncio.run(ipo.fetch_ipo_calendar([month]))
    assert result['status'] == 'partial'
    assert result['events'] == old['events']
    assert result['stale_months'] == ['2026-11']
    assert 'copia' in result['errors'][0]
    assert old['status'] == 'ok' and old['errors'] == []


def test_fresh_calendar_has_no_stale_months(monkeypatch):
    month = date(2026, 11, 1)
    old = {'status': 'ok', 'month': '2026-11', 'errors': [], 'events': []}
    monkeypatch.setattr(ipo, '_month_cache', {month: (time.monotonic(), old)})
    result = asyncio.run(ipo.fetch_ipo_calendar([month]))
    assert result['status'] == 'ok'
    assert result['stale_months'] == []
