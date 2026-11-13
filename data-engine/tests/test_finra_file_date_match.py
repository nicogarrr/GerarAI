"""A RegSHO row must belong to the file that was actually retrieved."""
import asyncio
from datetime import date
from unittest.mock import Mock

import httpx
import pytest

from app.services.connectors import short_interest as si


@pytest.mark.parametrize('row_day', ['20261112', '20261114'])
def test_wrong_file_day_fails_closed_without_lookback(monkeypatch, row_day):
    calls = []
    registry = Mock()
    monkeypatch.setattr(si, 'get_data_source_registry', lambda: registry)
    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, text='Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n'
                              f'{row_day}|ABC|10|0|100|Q\n')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await si.fetch_short_volume('ABC', date(2026, 11, 13), client=client)
    assert asyncio.run(run()) is None
    assert len(calls) == 1
    registry.record_failure.assert_called_once()
    registry.record_success.assert_not_called()
