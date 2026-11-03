"""El ticker que trae un feed por consulta (GDELT/RSS) no vincula siglas ambiguas sin cita.

Repro real (news ids 411767/411828): GDELT busca por empresa con
«("C3.ai, Inc." OR AI)» y «AI» casa con cualquier articulo del sector IA; el
titular «Profitmind Launches Awase, Bringing Competitive Intelligence to Every
Product a Retailer Sells» quedo vinculado a C3.ai (ticker AI) por el ticker
del feed, sin que el texto citara a la empresa. Para siglas que son palabras
corrientes (AI, ALL, IT, ON, A...) o de nombre estricto (CPT, AENA), el
vinculo por ticker de feed exige que el texto cite a la empresa. Los carriles
autoritativos (SEC por CIK, IR de la propia empresa) y el envio manual por la
API conservan el vinculo directo.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.schemas.api import NewsFeedItem
from app.services.news_service import NewsService, _feed_ticker_needs_evidence

PROFITMIND_HEADLINE = (
    "Profitmind Launches Awase, Bringing Competitive Intelligence "
    "to Every Product a Retailer Sells"
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str, name: str) -> Company:
    company = Company(
        ticker=ticker, name=name, exchange="NYSE", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _ingest(db: Session, item: NewsFeedItem, connector: str | None):
    return NewsService().ingest_news_items(db, [item], connector=connector)


def test_needs_evidence_marks_common_word_tickers():
    for ticker in ("AI", "ALL", "IT", "ON", "A", "T", "NOW", "CPT", "AENA"):
        assert _feed_ticker_needs_evidence(ticker), ticker
        assert _feed_ticker_needs_evidence(ticker.lower()), ticker
    for ticker in ("MSFT", "ASTS", "NVDA", "CGEO.L", "BRK.B"):
        assert not _feed_ticker_needs_evidence(ticker), ticker


def test_gdelt_sector_article_does_not_link_to_c3ai(db):
    """El titular de Profitmind con ticker de feed AI NO se vincula a C3.ai."""
    c3ai = _company(db, "AI", "C3.ai, Inc.")
    result = _ingest(
        db,
        NewsFeedItem(
            ticker="AI",
            title=PROFITMIND_HEADLINE,
            text="Profitmind announced the launch of Awase, a competitive intelligence platform.",
            source="GlobeNewswire",
            url="https://wire.test/profitmind-awase",
        ),
        connector="gdelt",
    )
    assert result.created == 1
    assert result.events[0].ticker != c3ai.ticker
    assert result.events[0].ticker is None


def test_gdelt_legit_c3ai_brand_headline_still_links(db):
    """La noticia que cita la marca «C3.ai» si se vincula con el ticker del feed."""
    c3ai = _company(db, "AI", "C3.ai, Inc.")
    result = _ingest(
        db,
        NewsFeedItem(
            ticker="AI",
            title="C3.ai Announces Date for Third Quarter Fiscal 2027 Financial Results",
            text="C3.ai will release results after market close.",
            source="GlobeNewswire",
            url="https://wire.test/c3ai-q3-date",
        ),
        connector="gdelt",
    )
    assert result.created == 1
    assert result.events[0].ticker == c3ai.ticker


def test_gdelt_legit_c3ai_exchange_anchor_still_links(db):
    c3ai = _company(db, "AI", "C3.ai, Inc.")
    result = _ingest(
        db,
        NewsFeedItem(
            ticker="AI",
            title="C3.ai (NYSE: AI) Reports Fiscal Second Quarter Results",
            text=None,
            source="feed",
            url="https://wire.test/c3ai-q2",
        ),
        connector="gdelt",
    )
    assert result.created == 1
    assert result.events[0].ticker == c3ai.ticker


def test_sec_lane_keeps_authoritative_ticker_link(db):
    """Un filing SEC (CIK de la empresa) se vincula aunque el titular no la cite."""
    c3ai = _company(db, "AI", "C3.ai, Inc.")
    result = _ingest(
        db,
        NewsFeedItem(
            ticker="AI",
            title="8-K presentado ante la SEC",
            text=None,
            source="SEC",
            url="https://www.sec.gov/Archives/edgar/data/1577526/000157752626000123/a.htm",
        ),
        connector="sec",
    )
    assert result.created == 1
    assert result.events[0].ticker == c3ai.ticker


def test_manual_api_submission_keeps_explicit_ticker(db):
    """El envio manual por la API (connector=None) es explicito: vinculo directo."""
    c3ai = _company(db, "AI", "C3.ai, Inc.")
    result = _ingest(
        db,
        NewsFeedItem(
            ticker="AI",
            title="Nota sobre el sector de inteligencia artificial",
            text=None,
            source="manual",
            url=None,
        ),
        connector=None,
    )
    assert result.created == 1
    assert result.events[0].ticker == c3ai.ticker


def test_unambiguous_feed_ticker_keeps_direct_link(db):
    """Tickers sin ambiguedad: el vinculo directo del feed no cambia."""
    msft = _company(db, "MSFT", "Microsoft Corporation")
    result = _ingest(
        db,
        NewsFeedItem(
            ticker="MSFT",
            title="Unrelated headline with no company mention at all",
            text=None,
            source="feed",
            url="https://wire.test/unrelated",
        ),
        connector="gdelt",
    )
    assert result.created == 1
    assert result.events[0].ticker == msft.ticker


def test_gdelt_strict_ticker_visa_headline_does_not_link(db):
    """CPT (visado de estudiantes) con ticker de feed: sin cita de Camden, no vincula."""
    _company(db, "CPT", "Camden Property Trust")
    result = _ingest(
        db,
        NewsFeedItem(
            ticker="CPT",
            title="CPT Work Authorization Guide for F-1 Students in 2026",
            text="Curricular Practical Training lets students work during their studies.",
            source="feed",
            url="https://wire.test/cpt-visa",
        ),
        connector="gdelt",
    )
    assert result.created == 1
    assert result.events[0].ticker is None


def test_gdelt_strict_ticker_legit_headline_still_links(db):
    camden = _company(db, "CPT", "Camden Property Trust")
    result = _ingest(
        db,
        NewsFeedItem(
            ticker="CPT",
            title="Camden Property Trust Reports Third Quarter Results",
            text="The REIT posted quarterly funds from operations above consensus.",
            source="feed",
            url="https://wire.test/cpt-q3",
        ),
        connector="gdelt",
    )
    assert result.created == 1
    assert result.events[0].ticker == camden.ticker
