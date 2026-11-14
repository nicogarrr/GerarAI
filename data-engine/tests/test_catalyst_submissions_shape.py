"""Malformed SEC submissions must show unavailable, not a silent empty calendar."""
import asyncio
from datetime import date

import pytest

from app.services import catalyst_calendar_service as service


@pytest.mark.parametrize('data', [
    {'filings': None}, {'filings': []}, {'filings': 'bad'}, {'filings': {'recent': []}}, {'filings': {'recent': None}},
    {'filings': {'recent': {'form': '10-Q', 'reportDate': ['2026-06-30']}}},
    {'filings': {'recent': {'form': ['10-Q'], 'reportDate': '2026-06-30'}}},
    {'filings': {'recent': {'form': {}, 'reportDate': []}}},
])
def test_malformed_sec_fields_are_visible_as_unavailable(monkeypatch, data):
    monkeypatch.setattr(service, '_FAILED_UNTIL', {})
    async def cik(ticker):
        return '123'
    async def submissions(cik):
        return data
    result = asyncio.run(service.fetch_filing_deadlines(
        {'TEST'}, date(2026, 1, 1), date(2027, 12, 31),
        cik_fetcher=cik, submissions_fetcher=submissions,
    ))
    assert result['events'] == []
    assert result['status'] == 'unavailable'
    assert result['errors'] == ['Plazos 10-Q/10-K: EDGAR no disponible para TEST']
