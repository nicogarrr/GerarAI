"""A Finnhub envelope without a calendar must not confirm absence of earnings."""
import asyncio
from types import SimpleNamespace

import pytest

from app.services.company_events_service import CompanyEventsService


@pytest.mark.parametrize('payload', [{}, {'error': 'not available'}, {'earningsCalendar': None}])
def test_missing_calendar_is_unavailable_with_notice(payload):
    service = CompanyEventsService(None, calendar_fetcher=lambda *_: asyncio.sleep(0, payload),
                                   eps_history_fetcher=lambda _: asyncio.sleep(0, []))
    result = asyncio.run(service.get_events(SimpleNamespace(ticker='ABC', name='ABC')))
    assert result['calendar_status'] == 'unavailable'
    assert result['note']


def test_explicit_empty_calendar_remains_successful():
    service = CompanyEventsService(None, calendar_fetcher=lambda *_: asyncio.sleep(0, {'earningsCalendar': []}),
                                   eps_history_fetcher=lambda _: asyncio.sleep(0, []))
    result = asyncio.run(service.get_events(SimpleNamespace(ticker='ABC', name='ABC')))
    assert result['calendar_status'] == 'ok'
    assert result['note'] is None
