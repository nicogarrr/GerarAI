"""GDELT: solo se ingieren artículos en inglés/español (o idioma desconocido)."""

import asyncio

from app.services.connectors.gdelt import GDELTConnector


class _FakeClient:
    def __init__(self, articles):
        self._articles = articles

    async def news_search(self, query, max_records=50):
        return {"articles": self._articles}


def _article(url, language):
    return {
        "url": url,
        "title": f"Title for {url}",
        "seendate": "20261018T120000Z",
        "domain": "example.com",
        "language": language,
    }


def test_poll_skips_known_non_en_es_languages():
    articles = [
        _article("https://x.test/en", "English"),
        _article("https://x.test/es", "Spanish"),
        _article("https://x.test/ru", "Russian"),
        _article("https://x.test/de", "German"),
        _article("https://x.test/unknown", None),
    ]
    connector = GDELTConnector(client=_FakeClient(articles))
    result = asyncio.run(connector.poll("gold OR oro"))
    urls = [item.url for item in result.items]
    assert urls == ["https://x.test/en", "https://x.test/es", "https://x.test/unknown"]
