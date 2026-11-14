"""Falsey malformed matches are failures, never cached as no coverage."""
import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

from app.services.connectors import openfigi as o


@pytest.mark.parametrize('mode', ['sync', 'async'])
@pytest.mark.parametrize('value', [{}, False, 0, '', 'bad', [None]])
def test_malformed_matches_fail_without_success_or_cache(monkeypatch, mode, value):
    registry = MagicMock()
    monkeypatch.setattr(o, 'get_data_source_registry', lambda: registry)
    handler = lambda _: httpx.Response(200, json=[{'data': value}])
    if mode == 'sync':
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            connector = o.OpenFIGIConnector(client=client, max_retries=0)
            with pytest.raises(RuntimeError, match='invalid mapping matches'):
                connector.map_identifier('EXAMPLE')
            assert len(connector.cache) == 0
    else:
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await o.OpenFIGIClient(client).map_identifier('EXAMPLE')
        with pytest.raises(RuntimeError, match='invalid mapping matches'):
            asyncio.run(run())
    registry.record_failure.assert_called_once()
    registry.record_success.assert_not_called()


@pytest.mark.parametrize('mode', ['sync', 'async'])
@pytest.mark.parametrize('body,status', [({}, 'unavailable'), ({'data': None}, 'unavailable'), ({'data': []}, 'unavailable'), ({'warning': 'No identifiers found.'}, 'unavailable'), ({'error': 'No match'}, 'error'), ({'data': [{'figi': 'BBG1'}]}, 'matched'), ({'data': [{'figi': 'BBG1'}, {'figi': 'BBG2'}]}, 'ambiguous')])
def test_existing_contract_is_preserved(monkeypatch, mode, body, status):
    registry = MagicMock()
    monkeypatch.setattr(o, 'get_data_source_registry', lambda: registry)
    handler = lambda _: httpx.Response(200, json=[body])
    if mode == 'sync':
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            connector = o.OpenFIGIConnector(client=client, max_retries=0)
            result = connector.map_identifier('EXAMPLE')
            assert len(connector.cache) == 1
    else:
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await o.OpenFIGIClient(client).map_identifier('EXAMPLE')
        result = asyncio.run(run())
    assert result['status'] == status
    registry.record_failure.assert_not_called()
    registry.record_success.assert_called_once()
