"""Unreadable CNMV percentages are source drift, not an invisible exception."""
import asyncio
from decimal import InvalidOperation

import httpx
import pytest

from app.services.connectors import cnmv_shorts as connector
from tests.test_cnmv_shorts_fetch_edges import ISSUER, _page


@pytest.mark.parametrize('percent', ['', '--', 'not-a-number'])
def test_unreadable_percent_records_source_failure(monkeypatch, percent):
    outcomes = []
    class Registry:
        def record_failure(self, source, reason):
            outcomes.append((source, 'failure'))
        def record_success(self, source):
            outcomes.append((source, 'success'))
    monkeypatch.setattr(connector, 'get_data_source_registry', lambda: Registry())
    body = _page(f'<tr><td>Fund</td><td>{percent}</td><td>01/01/2026</td><td></td></tr>')
    async def probe():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=body)
        )) as client:
            with pytest.raises((ValueError, InvalidOperation)):
                await connector.fetch_positions(ISSUER, client=client)
    asyncio.run(probe())
    assert outcomes == [('cnmv', 'failure')]
