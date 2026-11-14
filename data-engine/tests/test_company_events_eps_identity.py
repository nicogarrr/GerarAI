"""A symbol in an upstream EPS row must not contradict the requested company."""
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.company_events_service import CompanyEventsService


@pytest.mark.parametrize('mixed', [False, True])
def test_eps_of_another_symbol_is_not_reported_for_this_company(mixed):
    period = (datetime.now(UTC).date() - timedelta(days=30)).isoformat()
    rows = [{'symbol': 'OTHER', 'period': period, 'actual': 999, 'estimate': 1}]
    if mixed:
        rows.append({'symbol': 'REQUESTED', 'period': period, 'actual': 2, 'estimate': 1})
    service = CompanyEventsService(None,
        calendar_fetcher=lambda *a: asyncio.sleep(0, {'earningsCalendar': []}),
        eps_history_fetcher=lambda *a: asyncio.sleep(0, rows))
    out = asyncio.run(service.get_events(SimpleNamespace(ticker='REQUESTED', name='Requested')))
    assert out['eps_history_status'] == ('partial' if mixed else 'unavailable')
    assert out['note']
    if mixed:
        assert out['history'][0]['eps_actual'] == 2
        assert 'símbolo' in out['note']
    else:
        assert out['history'] == []
