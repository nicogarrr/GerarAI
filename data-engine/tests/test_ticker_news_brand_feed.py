"""Feed de marca en Google News (SPCX: «SpaceX», «Starlink»).

Caso real: el estudio de Ookla del 3-nov-2026 «Testing the limits of
Starlink's D2D text and data performance in the U.S.» no llegó a la app: la
consulta por nombre legal («"Space Exploration Technologies" OR SPCX») no lo
trae y el feed de Yahoo por símbolo tampoco.
"""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from app.services.connectors.base import ConnectorItem, ConnectorResult
from app.services.news_service import _ticker_evidence_level
from app.services.ticker_news_lane import (
    QUERY_ALIASES,
    VERIFIED_ALIASES,
    google_alias_feed_url,
    google_feed_url,
    google_lanes,
    label_google,
)

SPCX = SimpleNamespace(ticker="SPCX", name="Space Exploration Technologies Corp", exchange="NASDAQ")
ASTS = SimpleNamespace(ticker="ASTS", name="AST SpaceMobile Inc", exchange="NASDAQ")
MSFT = SimpleNamespace(ticker="MSFT", name="Microsoft Corp", exchange="NASDAQ")
OOKLA = "Testing the limits of Starlink’s D2D text and data performance in the U.S. - Ookla"


def _query(url: str) -> str:
    return parse_qs(urlsplit(url).query)["q"][0]


def test_name_query_alone_cannot_reach_brand_only_headlines():
    q = _query(google_feed_url(SPCX))
    assert q == '"Space Exploration Technologies" OR SPCX'
    assert "Starlink" not in q


def test_alias_feed_searches_the_brands_recent_only():
    q = _query(google_alias_feed_url(SPCX))
    assert q == '"SpaceX" OR "Starlink" when:7d'


def test_alias_feed_only_for_verified_distinctive_brands():
    # ASTS («BlueBird» es también una marca de autobuses) y MSFT (marcas
    # amplias) no tienen feed de marca.
    assert google_alias_feed_url(ASTS) is None
    assert google_alias_feed_url(MSFT) is None
    for ticker, aliases in QUERY_ALIASES.items():
        verified = {a.casefold() for a in VERIFIED_ALIASES.get(ticker, ())}
        assert all(a.casefold() in verified for a in aliases), ticker


def test_lanes_add_the_brand_feed_without_dropping_the_name_feeds():
    lanes = dict(google_lanes(SPCX, priority=True))
    assert set(lanes) == {"google-en", "google-es", "google-en-marca"}
    assert lanes["google-en"] == google_feed_url(SPCX, lang="en")
    assert [lane for lane, _ in google_lanes(ASTS, priority=False)] == ["google-en"]


def test_ookla_headline_from_brand_feed_is_kept_with_its_real_source():
    result = ConnectorResult(
        source="rss",
        items=[
            ConnectorItem(source="Google News", title=OOKLA, summary="", ticker="SPCX"),
            ConnectorItem(source="Google News", title="Mobile carriers expand 5G - Light Reading", summary="", ticker="SPCX"),
        ],
    )
    kept = label_google(result, SPCX, _ticker_evidence_level).items
    assert [(i.title, i.source) for i in kept] == [
        ("Testing the limits of Starlink’s D2D text and data performance in the U.S.", "Ookla")
    ]
