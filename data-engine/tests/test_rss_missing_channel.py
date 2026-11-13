"""Una raíz RSS no basta para confirmar un feed vacío válido."""
import asyncio

import httpx
import pytest

from app.services.connectors import rss


@pytest.mark.parametrize('body', [b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>', b'<rss/>', b'<rss><error>Unavailable</error></rss>',
    b'<rss><item><title>Not a valid RSS 2 feed</title></item></rss>'])
def test_rss_without_channel_is_failure_not_empty_success(body):
    async def poll():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=body)
        )) as client:
            return await rss.RSSConnector(client).poll('https://issuer.example/feed')
    result = asyncio.run(poll())
    assert result.status == "error"
    assert result.items == []


def test_valid_empty_channel_stays_success():
    async def poll():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b'<rss><channel><title>Issuer</title></channel></rss>')
        )) as client:
            return await rss.RSSConnector(client).poll('https://issuer.example/feed')
    result = asyncio.run(poll())
    assert result.status == "ok"
    assert result.items == []
    assert result.metadata['feed_title'] == 'Issuer'
