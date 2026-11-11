"""IR links use the fetched page URL, not the URL before redirects. No network."""

import asyncio

import httpx

from app.services.connectors import ir


def test_public_fetch_final_url_is_base_for_root_and_newsroom(monkeypatch):
    requested = []

    async def fetch(url, **kwargs):
        requested.append(url)
        if len(requested) == 1:
            return (
                b'<html><a href="news/">News</a></html>',
                'text/html',
                'https://investors.example/en/',
            )
        return (
            b'<html><a href="press-release/results">Results</a></html>',
            'text/html',
            'https://investors.example/en/archive/',
        )

    monkeypatch.setattr(ir, 'fetch_public_url_async', fetch)
    result = asyncio.run(ir.IRConnector().poll('https://old.example/ir', ticker='TEST'))
    assert requested == ['https://old.example/ir', 'https://investors.example/en/news/']
    assert [item.url for item in result.items] == [
        'https://investors.example/en/archive/press-release/results',
    ]
    assert result.metadata['ir_url'] == 'https://old.example/ir'
    assert result.metadata['final_ir_url'] == 'https://investors.example/en/'
    assert result.metadata['pages_polled'] == ['https://investors.example/en/archive/']


def test_injected_client_uses_response_url_after_redirect():
    def handle(request):
        if request.url.host == 'old.example':
            return httpx.Response(302, headers={'location': 'https://investors.example/en/'})
        return httpx.Response(200, text='<html><a href="press-release/results">Results</a></html>')

    async def poll():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
            return await ir.IRConnector(client).poll('https://old.example/ir')

    result = asyncio.run(poll())
    assert [item.url for item in result.items] == ['https://investors.example/en/press-release/results']
