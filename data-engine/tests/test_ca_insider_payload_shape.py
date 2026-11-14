"""Explicitly malformed Yahoo transaction collections are not no activity."""
import asyncio

import httpx
import pytest

from app.services.ca_insider_ingestion import ingest_ca_insiders
from app.services.connectors import ca_insider_yahoo as service
from app.services.data_source_health import get_data_source_registry
from tests.test_ca_insider_ingestion import RECORDED_BN, _no_sleep, db  # noqa: F401

BAD = [[None], [{'insiderTransactions': False}], [{'insiderTransactions': 'bad'}],
       [{'insiderTransactions': {'transactions': 'bad'}}],
       [{'insiderTransactions': {'transactions': {}}}],
       [{'insiderTransactions': {'transactions': False}}],
       [{'insiderTransactions': {'transactions': [None]}}]]


def fetch(result):
    payload = {'quoteSummary': {'error': None, 'result': result}}
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))) as client:
        return service.fetch_insider_transactions('BN', client, 'crumb')


@pytest.mark.parametrize('result', BAD)
def test_malformed_transactions_record_failure_not_success(result):
    registry = get_data_source_registry()
    before = registry.get_status('yahoo_finance').consecutive_failures
    with pytest.raises(ValueError):
        fetch(result)
    assert registry.get_status('yahoo_finance').consecutive_failures == before + 1


@pytest.mark.parametrize('result', [[], [{}], [{'insiderTransactions': None}],
                                  [{'insiderTransactions': {}}],
                                  [{'insiderTransactions': {'transactions': None}}],
                                  [{'insiderTransactions': {'transactions': []}}]])
def test_absent_module_and_empty_collection_stay_empty(result):
    assert fetch(result) == []


def test_valid_transactions_unchanged_from_parent():
    # Same recorded payload compared against the parent before this guard.
    assert fetch([{'insiderTransactions': {'transactions': RECORDED_BN}}]) == RECORDED_BN


def test_ingestion_reports_format_error_not_zero_activity(db, monkeypatch):
    monkeypatch.setattr('app.services.ca_insider_ingestion.fetch_insider_transactions',
                        lambda *args: fetch(BAD[3]))
    monkeypatch.setattr('app.services.ca_insider_ingestion.asyncio.sleep', _no_sleep)
    result = asyncio.run(ingest_ca_insiders(db, 1, client=None, crumb='crumb'))
    assert result['saved'] == 0
    assert all(value == {'error': 'ValueError'} for value in result['tickers'].values())
