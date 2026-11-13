"""SEC publication dates must be verifiable before listing observed filings."""
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.company_events_service import CompanyEventsService


@pytest.mark.parametrize('invalid_day', [None, 'not-a-date', '2999-01-01'])
def test_filings_skip_unverifiable_publication_dates_and_warn(invalid_day):
    today = datetime.now(UTC).date()
    payload = {'filings': {'recent': {
        'accessionNumber': ['0000320193-26-000001', '0000320193-26-000002'],
        'form': ['10-Q', '8-K'],
        'primaryDocument': ['q.htm', 'k.htm'],
        'filingDate': [invalid_day, today.isoformat()],
        'reportDate': ['2026-06-30', '2026-09-30'],
    }}}
    service = CompanyEventsService(None, submissions_fetcher=lambda _: asyncio.sleep(0, payload))
    service._db_documents = lambda *_: []
    company = SimpleNamespace(ticker='AAPL', name='Apple', cik='0000320193')
    out = asyncio.run(service.get_filings(company, limit=1))
    assert [row['accession'] for row in out['filings']] == ['0000320193-26-000002']
    assert out['sec_status'] == 'partial'
    assert 'fecha de presentación' in out['note']


def test_verified_filing_today_and_yesterday_remain_available():
    today = datetime.now(UTC).date()
    recent = {'accessionNumber': ['0000320193-26-000001', '0000320193-26-000002'],
              'form': ['10-Q', '8-K'], 'filingDate': [(today-timedelta(days=1)).isoformat(), today.isoformat()]}
    service = CompanyEventsService(None, submissions_fetcher=lambda _: asyncio.sleep(0, {'filings': {'recent': recent}}))
    service._db_documents = lambda *_: []
    company = SimpleNamespace(ticker='AAPL', name='Apple', cik='0000320193')
    out = asyncio.run(service.get_filings(company))
    assert len(out['filings']) == 2
    assert out['sec_status'] == 'ok'
    assert out['note'] is None
