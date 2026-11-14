"""GDELT malformed JSON is an error, not a healthy empty news batch."""
import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

from app.services.connectors import gdelt as g
from app.services.feed_ingestion_service import FeedIngestionService


@pytest.fixture
def registry(monkeypatch):
    registry = MagicMock()
    monkeypatch.setattr(g, 'get_data_source_registry', lambda: registry)

    async def no_throttle(self):
        pass

    monkeypatch.setattr(g.GDELTClient, '_throttle', no_throttle)
    return registry


INVALID = [[], None, 1, 'bad', {'articles': None}, {'articles': {}}, {'articles': 'bad'}, {'articles': [None]}, {'articles': [{'title': 'valid'}, 1]}]


@pytest.mark.parametrize('payload', INVALID)
def test_search_rejects_malformed_payload_before_success(registry, payload):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
            return await g.GDELTClient(client).news_search('EXAMPLE')

    with pytest.raises(ValueError):
        asyncio.run(run())
    registry.record_failure.assert_called_once()
    registry.record_success.assert_not_called()


@pytest.mark.parametrize('payload', INVALID)
def test_poll_returns_error_and_ingestion_stays_empty(registry, payload):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
            return await g.GDELTConnector(g.GDELTClient(client)).poll('EXAMPLE')

    result = asyncio.run(run())
    assert result.status == 'error'
    assert result.errors
    assert result.items == []
    db = MagicMock()
    ingested = FeedIngestionService().ingest_news_result(db, result)
    assert ingested['status'] == 'error'
    assert ingested['created'] == 0
    assert ingested['received'] == 0
    assert ingested['errors'] == result.errors
    assert db.mock_calls == []
    registry.record_failure.assert_called_once()
    registry.record_success.assert_not_called()


@pytest.mark.parametrize('payload', [{}, {'articles': []}, {'articles': [{'title': 'Example', 'url': 'https://example.test/news'}]}])
def test_search_preserves_empty_and_valid_contract(registry, payload):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
            return await g.GDELTClient(client).news_search('EXAMPLE')

    assert asyncio.run(run()) == payload
    registry.record_failure.assert_not_called()
    registry.record_success.assert_called_once()
