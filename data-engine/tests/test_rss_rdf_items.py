"""RSS 1.0/RDF stores news beside channel, not inside channel."""
import asyncio

import httpx

from app.services.connectors.rss import RSSConnector

RDF = b'''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
 <channel rdf:about="https://issuer.example/feed"><title>Issuer news</title>
 <items><rdf:Seq><rdf:li rdf:resource="https://issuer.example/results"/></rdf:Seq></items>
 </channel>
 <item rdf:about="https://issuer.example/results"><title>Quarterly results</title>
 <link>https://issuer.example/results</link><description>Revenue reported</description>
 <dc:date>2026-11-13T08:00:00Z</dc:date><dc:creator>Issuer</dc:creator></item>
</rdf:RDF>'''


def test_rdf_items_are_not_reported_as_successfully_empty():
    async def poll():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=RDF)
        )) as client:
            return await RSSConnector(client).poll('https://issuer.example/feed', ticker='ABC')
    result = asyncio.run(poll())
    assert len(result.items) == 1
    item = result.items[0]
    assert item.source == 'Issuer news'
    assert item.title == 'Quarterly results'
    assert item.url == 'https://issuer.example/results'
    assert item.published_at.isoformat() == '2026-11-13T08:00:00+00:00'
    assert item.metadata['author'] == 'Issuer'
    assert item.ticker == 'ABC'
