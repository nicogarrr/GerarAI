"""Un updated antes de published no convierte una noticia antigua en nueva."""
import asyncio

import httpx
import pytest

from app.services.connectors.rss import RSSConnector


@pytest.mark.parametrize('dates', [
    '<updated>2026-11-13T10:00:00Z</updated><published>2026-10-01T09:00:00Z</published>',
    '<published>2026-10-01T09:00:00Z</published><updated>2026-11-13T10:00:00Z</updated>',
])
def test_publication_date_wins_independent_of_xml_order(dates):
    body = ('<feed xmlns="http://www.w3.org/2005/Atom"><title>Wire</title>'
            '<entry><title>Old results, updated</title>' + dates + '</entry></feed>').encode()
    result = _poll(body)
    assert result.status == 'ok'
    assert result.items[0].published_at.isoformat() == '2026-10-01T09:00:00+00:00'


def test_updated_is_not_publication_when_publication_absent():
    """<updated> es fecha de modificación, no de publicación: no se promociona.

    Contrato nuevo (Lote 1, hallazgo 4): con solo <updated>, published_at
    queda None y la ingesta declara date_source=ingested_at_fallback, igual
    que GDELT con su seendate. El valor de <updated> se conserva visible en
    metadata["updated_at"] en vez de fingir frescura.
    """
    result = _poll(b'<feed><entry><title>Update</title><updated>2026-11-13T10:00:00Z</updated></entry></feed>')
    assert result.items[0].published_at is None
    assert result.items[0].metadata["updated_at"] == '2026-11-13T10:00:00+00:00'


def _poll(body):
    async def poll():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=body)
        )) as client:
            return await RSSConnector(client).poll('https://issuer.example/atom')
    return asyncio.run(poll())
