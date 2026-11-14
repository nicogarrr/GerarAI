"""Las columnas SEC son listas, no cadenas ni mapas indexables."""
import asyncio
from types import SimpleNamespace

import pytest

from app.services.company_events_service import CompanyEventsService


def _get(payload):
    service = CompanyEventsService(None, submissions_fetcher=lambda _: asyncio.sleep(0, payload))
    service._db_documents = lambda *_: []
    return asyncio.run(service.get_filings(SimpleNamespace(ticker='AAPL', name='Apple', cik='0000320193')))


@pytest.mark.parametrize('column', ['accessionNumber', 'form', 'filingDate', 'reportDate', 'primaryDocument'])
@pytest.mark.parametrize('invalid', ['', 'ilegible', {}, {'0': 'valor'}, 1, None])
def test_malformed_columns_never_claim_verified_empty_index(column, invalid):
    recent = {'accessionNumber': ['0000320193-26-000001'], 'form': ['10-Q'],
              'filingDate': ['2026-08-01'], 'reportDate': ['2026-06-30'], 'primaryDocument': ['q.htm']}
    recent[column] = invalid
    out = _get({'filings': {'recent': recent}})
    assert out['sec_status'] == 'unavailable'
    assert out['filings'] == []
    assert 'estructura' in out['note']


def test_explicit_empty_list_columns_are_verified_empty():
    out = _get({'filings': {'recent': {'accessionNumber': [], 'form': [], 'filingDate': []}}})
    assert out['sec_status'] == 'ok'
    assert out['filings'] == []
