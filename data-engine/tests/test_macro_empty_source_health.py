"""An HTTP 200 without any parsed official events is not source recovery."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.connectors import macro_calendar as connector
from app.services.data_source_health import DataSourceHealthRegistry


@pytest.mark.parametrize('fetch,key,body', [
    (connector.fetch_fomc, 'fomc_calendar', '<html>Access Denied</html>'),
    (connector.fetch_fomc, 'fomc_calendar', '<html>Changed markup</html>'),
    (connector.fetch_bls, 'bls_calendar', 'BEGIN:VCALENDAR\r\nEND:VCALENDAR'),
    (connector.fetch_bls, 'bls_calendar', 'BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Employment Situation\r\nDTSTART:invalid\r\nEND:VEVENT\r\nEND:VCALENDAR'),
])
def test_empty_parsed_calendar_does_not_clear_prior_failures(fetch, key, body, monkeypatch):
    registry = DataSourceHealthRegistry()
    monkeypatch.setattr(connector, "get_data_source_registry", lambda: registry)
    state = registry.get_status(key)
    registry.record_failure(key, 'prior failure')
    before = state.consecutive_failures

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=body, request=request)
        )) as client:
            with pytest.raises(ValueError):
                await fetch('GerarAI test (contact@example.com)', client)

    asyncio.run(run())
    assert state.consecutive_failures == before + 1
