"""Un JSON sin índice SEC no es una consulta de filings verificada."""
import asyncio
from types import SimpleNamespace

import pytest

from app.services.company_events_service import CompanyEventsService


@pytest.mark.parametrize('payload', [
    {}, {'filings': None}, {'filings': []}, {'filings': 'error'},
    {'filings': {}}, {'filings': {'recent': None}},
    {'filings': {'recent': []}}, {'filings': {'recent': 'error'}},
])
def test_missing_or_malformed_sec_index_is_unavailable(payload):
    service = CompanyEventsService(None, submissions_fetcher=lambda _: asyncio.sleep(0, payload))
    service._db_documents = lambda *_: []
    out = asyncio.run(service.get_filings(SimpleNamespace(ticker='AAPL', name='Apple', cik='0000320193')))
    assert out['sec_status'] == 'unavailable'
    assert out['filings'] == []
    assert out['source'] is None
    assert out['note']


def test_explicit_empty_recent_dictionary_retains_existing_empty_index_contract():
    service = CompanyEventsService(None, submissions_fetcher=lambda _: asyncio.sleep(0, {'filings': {'recent': {}}}))
    service._db_documents = lambda *_: []
    out = asyncio.run(service.get_filings(SimpleNamespace(ticker='AAPL', name='Apple', cik='0000320193')))
    assert out['sec_status'] == 'ok'
    assert out['filings'] == []


def test_malformed_index_retains_imported_documents_and_explains_format_failure():
    document = {'title': 'Documento guardado', 'source_type': 'sec', 'url': None}
    service = CompanyEventsService(None, submissions_fetcher=lambda _: asyncio.sleep(0, {}))
    service._db_documents = lambda *_: [document]
    out = asyncio.run(service.get_filings(SimpleNamespace(ticker='AAPL', name='Apple', cik='0000320193')))
    assert out['documents'] == [document]
    assert out['sec_status'] == 'unavailable'
    assert 'estructura' in out['note']
    assert 'importados' in out['note']
