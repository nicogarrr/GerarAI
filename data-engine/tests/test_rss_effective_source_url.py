"""Redirected RSS links keep the effective feed origin. No external sockets."""

import asyncio

import httpx
import pytest

from app.services.connectors import rss

FEED = b'<rss><channel><title>Issuer</title><item><title>Results</title><link>results</link></item></channel></rss>'


@pytest.mark.parametrize('injected_client', [False, True])
def test_relative_link_uses_effective_feed_url(monkeypatch, injected_client):
    async def fetch(url, **kwargs):
        return FEED, 'application/rss+xml', 'https://investors.example/en/feed.xml'

    monkeypatch.setattr(rss, 'fetch_public_url_async', fetch)

    def handle(request):
        if request.url.host == 'old.example':
            return httpx.Response(302, headers={'location': 'https://investors.example/en/feed.xml'})
        return httpx.Response(200, content=FEED)

    async def poll():
        if not injected_client:
            return await rss.RSSConnector().poll('https://old.example/rss')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
            return await rss.RSSConnector(client).poll('https://old.example/rss')

    result = asyncio.run(poll())
    assert [item.url for item in result.items] == ['https://investors.example/en/results']
    assert result.items[0].external_id == 'https://investors.example/en/results'
    assert result.items[0].metadata['feed_url'] == 'https://investors.example/en/feed.xml'
    assert result.metadata['feed_url'] == 'https://old.example/rss'
    assert result.metadata['final_feed_url'] == 'https://investors.example/en/feed.xml'
