"""A symbol that cannot be queried is missing coverage, not a synced portfolio."""
import asyncio

import pytest

from app.services.dividend_ingestion_service import DividendIngestionService
from app.services.split_ingestion_service import SplitIngestionService


@pytest.mark.parametrize('service_type', [SplitIngestionService, DividendIngestionService])
@pytest.mark.parametrize(('statuses', 'synced', 'missing', 'coverage'), [
    (['no_safe_symbol'], 0, 1, 'unavailable'),
    (['ok', 'no_safe_symbol'], 1, 1, 'partial'),
    (['no_safe_symbol', 'unavailable', 'failed'], 0, 3, 'unavailable'),
    (['ok'], 1, 0, 'ok'),
    ([], 0, 0, 'ok'),
])
def test_no_safe_symbol_is_counted_as_unavailable(service_type, statuses, synced, missing, coverage, monkeypatch):
    service = service_type()
    results = [{'ticker': f'EX{i}', 'status': status, 'inserted': 0, 'existing': 0}
               for i, status in enumerate(statuses)]
    async def fake_sync(db, tickers):
        return results
    monkeypatch.setattr(service, '_portfolio_tickers', lambda db: ['EX'])
    monkeypatch.setattr(service, 'sync_each', fake_sync)
    result = asyncio.run(service.sync_portfolio(None))
    assert result['companies'] == len(statuses)
    assert result['synced'] == synced
    assert result['unavailable'] == missing
    assert result['provenance']['coverage'] == coverage
    assert result['results'] == results
