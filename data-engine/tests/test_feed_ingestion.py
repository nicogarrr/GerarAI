import asyncio

import httpx

from app.services.connectors.gdelt import GDELTConnector
from app.services.connectors.ir import IRConnector
from app.services.connectors.rss import RSSConnector
from app.services.connectors.sec import SECClient
from app.services.feed_ingestion_service import configured_rss_feeds


def run_async(coroutine):
    return asyncio.run(coroutine)


def test_rss_and_atom_polling_normalizes_items():
    rss = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Example Wire</title>
      <item>
        <title>Quarterly &amp; operating update</title>
        <link>/releases/q1</link>
        <description><![CDATA[<p>Revenue increased.</p>]]></description>
        <pubDate>Tue, 07 Jul 2026 12:00:00 GMT</pubDate>
        <guid>release-1</guid>
      </item>
    </channel></rss>"""
    atom = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Atom Wire</title>
      <entry>
        <title>New contract</title>
        <link rel="alternate" href="https://example.test/contract"/>
        <summary>Five year award</summary>
        <updated>2026-07-08T09:30:00Z</updated>
        <id>contract-1</id>
      </entry>
    </feed>"""

    async def poll_both():
        async def handler(request: httpx.Request) -> httpx.Response:
            content = atom if request.url.path == "/atom" else rss
            return httpx.Response(200, content=content, request=request)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            connector = RSSConnector(client)
            return (
                await connector.poll("https://example.test/rss", ticker="MSFT"),
                await connector.poll("https://example.test/atom"),
            )

    rss_result, atom_result = run_async(poll_both())

    assert rss_result.status == "ok"
    assert rss_result.items[0].url == "https://example.test/releases/q1"
    assert rss_result.items[0].summary == "Revenue increased."
    assert rss_result.items[0].ticker == "MSFT"
    assert rss_result.items[0].published_at.isoformat() == "2026-07-07T12:00:00+00:00"
    assert atom_result.metadata["format"] == "atom"
    assert atom_result.items[0].external_id == "contract-1"


def test_gdelt_connector_uses_existing_client_and_deduplicates():
    class FakeGDELTClient:
        def __init__(self):
            self.calls = []

        async def news_search(self, query: str, max_records: int = 50):
            self.calls.append((query, max_records))
            article = {
                "url": "https://wire.test/story",
                "title": "Material customer win",
                "domain": "wire.test",
                "seendate": "20260708T093000Z",
            }
            return {"articles": [article, article]}

    client = FakeGDELTClient()
    result = run_async(
        GDELTConnector(client).poll("Microsoft OR MSFT", ticker="MSFT", max_records=12)
    )

    assert client.calls == [("Microsoft OR MSFT", 12)]
    assert result.status == "ok"
    assert len(result.items) == 1
    assert result.items[0].published_at.isoformat() == "2026-07-08T09:30:00+00:00"


def test_sec_recent_filings_uses_identity_and_builds_archive_urls():
    seen_requests = []
    payload = {
        "name": "Example Corp",
        "filings": {
            "recent": {
                "accessionNumber": ["0001234567-26-000010", "0001234567-26-000009"],
                "filingDate": ["2026-07-08", "2026-07-01"],
                "reportDate": ["2026-06-30", "2026-06-30"],
                "form": ["10-Q", "4"],
                "primaryDocument": ["example-20260630.htm", "ownership.xml"],
                "isInlineXBRL": [1, 0],
            }
        },
    }

    async def poll():
        async def handler(request: httpx.Request) -> httpx.Response:
            seen_requests.append(request)
            return httpx.Response(200, json=payload, request=request)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            sec = SECClient(
                client,
                user_agent="GerarAI tests engineering@example.com",
                requests_per_second=10,
            )
            return await sec.recent_filings(
                "1234567",
                forms={"10-Q"},
                ticker="TEST",
            )

    result = run_async(poll())

    assert seen_requests[0].headers["user-agent"] == "GerarAI tests engineering@example.com"
    assert result.status == "ok"
    assert len(result.items) == 1
    assert result.items[0].metadata["form"] == "10-Q"
    assert result.items[0].url == (
        "https://www.sec.gov/Archives/edgar/data/1234567/"
        "000123456726000010/example-20260630.htm"
    )
    assert SECClient.filing_index_url("0001234567", "0001234567-26-000010").endswith(
        "/1234567/000123456726000010/"
    )


def test_ir_poll_discovers_newsroom_and_release_links():
    root = """
    <html><body>
      <a href="/investors/news">News and press releases</a>
    </body></html>
    """
    newsroom = """
    <html><body>
      <a href="/news-releases/news-release-details/customer-award">
        Company wins a customer award
      </a>
      <a href="/investors/news">News archive</a>
    </body></html>
    """
    requested_paths = []

    async def poll():
        async def handler(request: httpx.Request) -> httpx.Response:
            requested_paths.append(request.url.path)
            content = newsroom if request.url.path == "/investors/news" else root
            return httpx.Response(200, text=content, request=request)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await IRConnector(client).poll(
                "https://investor.example.test",
                ticker="TEST",
            )

    result = run_async(poll())

    assert requested_paths == ["/", "/investors/news"]
    assert result.status == "ok"
    assert len(result.items) == 1
    assert result.items[0].item_type == "press_release"
    assert result.items[0].url.endswith("/news-release-details/customer-award")


def test_rss_feed_configuration_accepts_json_and_compact_syntax():
    feeds = configured_rss_feeds(
        '[{"url":"https://one.test/feed","ticker":"msft"},'
        '"TEST|https://two.test/rss","https://three.test/rss|NVDA"]'
    )

    assert [(feed.url, feed.ticker) for feed in feeds] == [
        ("https://one.test/feed", "MSFT"),
        ("https://two.test/rss", "TEST"),
        ("https://three.test/rss", "NVDA"),
    ]


def test_scheduler_jobs_are_single_instance_and_coalesced():
    from app.workers.scheduler import build_scheduler

    scheduler = build_scheduler()
    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert {
        "rss_refresh",
        "news_refresh",
        "ir_refresh",
        "sec_refresh",
        "contradiction_scan",
        "memory_consolidation",
        "thesis_review",
        "daily_research",
    } <= jobs.keys()
    assert all(job.max_instances == 1 and job.coalesce for job in jobs.values())


def test_actor_dependency_failure_returns_structured_error(monkeypatch):
    from app.workers import dramatiq_app

    def unavailable_session(*_args):
        raise ImportError("models are still loading")

    monkeypatch.setattr(dramatiq_app, "_session", unavailable_session)
    result = dramatiq_app.refresh_news.fn()

    assert result["status"] == "error"
    assert result["actor"] == "refresh_news"
    assert result["error"]["type"] == "ImportError"


def test_review_theses_is_scheduled_once_not_inside_daily_research():
    import inspect

    from app.workers import dramatiq_app

    source = inspect.getsource(dramatiq_app.run_daily_research.fn)
    assert "review_theses)" not in source.split("jobs: list", 1)[1].split("]", 1)[0]


def test_press_wire_feeds_are_builtin_and_merge_with_env_without_duplicates():
    from app.services.feed_ingestion_service import PRESS_WIRE_RSS_FEEDS, all_rss_feeds

    assert len(PRESS_WIRE_RSS_FEEDS) >= 3
    for feed in PRESS_WIRE_RSS_FEEDS:
        assert feed.url.startswith("https://")
        assert feed.ticker is None  # detección de empresa por contenido

    feeds = all_rss_feeds('TEST|https://two.test/rss')
    urls = [feed.url for feed in feeds]
    assert urls[: len(PRESS_WIRE_RSS_FEEDS)] == [f.url for f in PRESS_WIRE_RSS_FEEDS]
    assert ("https://two.test/rss", "TEST") in [(f.url, f.ticker) for f in feeds]

    # Un feed de agencia repetido en RSS_FEEDS no se pide dos veces.
    repeated = all_rss_feeds(PRESS_WIRE_RSS_FEEDS[0].url)
    assert [f.url for f in repeated].count(PRESS_WIRE_RSS_FEEDS[0].url) == 1


def test_configured_rss_feeds_stays_pure_without_builtin_wires():
    assert configured_rss_feeds("") == []
    assert [f.url for f in configured_rss_feeds("https://three.test/rss")] == [
        "https://three.test/rss"
    ]


def test_press_wire_feeds_carry_attribution_labels():
    from app.services.feed_ingestion_service import PRESS_WIRE_RSS_FEEDS, PRESS_WIRE_SOURCES

    labels = {feed.label for feed in PRESS_WIRE_RSS_FEEDS}
    assert labels == {"PR Newswire", "GlobeNewswire", "Business Wire"}
    # Las etiquetas nuevas y los <title> de canal históricos están cubiertos.
    assert labels <= PRESS_WIRE_SOURCES
    assert "All News Releases" in PRESS_WIRE_SOURCES


def test_poll_rss_relabels_items_when_source_label_is_set():
    from app.services.connectors.base import ConnectorItem, ConnectorResult
    from app.services.feed_ingestion_service import FeedIngestionService

    class FakeConnector:
        async def poll(self, url, *, ticker=None, max_items=100):
            return ConnectorResult(
                source="rss",
                items=[
                    ConnectorItem(source="All News Releases", title="Nota", url="https://x.test/1")
                ],
                metadata={"feed_title": "All News Releases"},
            )

    async def run():
        service = FeedIngestionService()
        return await service.poll_rss(
            "https://feeds.test/rss", connector=FakeConnector(), source_label="PR Newswire"
        )

    result = run_async(run())
    assert [item.source for item in result.items] == ["PR Newswire"]
    # La etiqueta original del canal sobrevive en metadata del poll.
    assert result.metadata["feed_title"] == "All News Releases"


def test_poll_rss_keeps_channel_title_without_source_label():
    from app.services.connectors.base import ConnectorItem, ConnectorResult
    from app.services.feed_ingestion_service import FeedIngestionService

    class FakeConnector:
        async def poll(self, url, *, ticker=None, max_items=100):
            return ConnectorResult(
                source="rss",
                items=[ConnectorItem(source="Apple Newsroom", title="Nota", url="https://x.test/2")],
            )

    async def run():
        return await FeedIngestionService().poll_rss("https://feeds.test/rss", connector=FakeConnector())

    result = run_async(run())
    assert [item.source for item in result.items] == ["Apple Newsroom"]


def test_gov_feeds_are_builtin_with_gobierno_lane():
    from app.services.feed_ingestion_service import GOV_NEWS_LANE, GOV_RSS_FEEDS, all_rss_feeds

    assert GOV_NEWS_LANE == "gobierno"
    assert len(GOV_RSS_FEEDS) >= 3  # Fed, BCE y Casa Blanca como mínimo
    for feed in GOV_RSS_FEEDS:
        assert feed.lane == GOV_NEWS_LANE
        assert feed.ticker is None
        assert feed.label and "(oficial)" in feed.label
        assert feed.url.startswith("https://")
    feeds = all_rss_feeds("")
    urls = {feed.url for feed in feeds}
    for feed in GOV_RSS_FEEDS:
        assert feed.url in urls


def test_gov_feeds_do_not_duplicate_env_feeds():
    from app.services.feed_ingestion_service import GOV_RSS_FEEDS, all_rss_feeds

    env_value = GOV_RSS_FEEDS[0].url
    feeds = all_rss_feeds(env_value)
    matching = [feed for feed in feeds if feed.url == GOV_RSS_FEEDS[0].url]
    assert len(matching) == 1
