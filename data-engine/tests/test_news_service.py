"""NewsService contract tests.

News ingestion feeds materiality and thesis reviews: tickers must match
on word boundaries only, duplicates must be skipped deterministically,
and ingest accounting must be exact.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, NewsEvent
from app.schemas.api import NewsFeedItem
from app.services.news_service import NewsService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str = "AAPL") -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_detect_ticker_respects_word_boundaries(db):
    apple = _company(db, "AAPL")
    service = NewsService()
    assert service.detect_ticker(db, "AAPL beats expectations") is apple
    # Substring inside another word must not match.
    assert service.detect_ticker(db, "The SNAPPIEST pineapple") is None
    assert service.detect_ticker(db, "no tickers here") is None


def test_company_for_item_prefers_explicit_ticker(db):
    apple = _company(db, "AAPL")
    service = NewsService()
    assert service._company_for_item(db, "some text", "aapl") is apple
    # Unknown explicit ticker falls back to text detection.
    assert service._company_for_item(db, "AAPL mentioned", "MSFT") is apple


def _event(db: Session, company: Company, *, title: str, url: str | None) -> NewsEvent:
    event = NewsEvent(
        company_id=company.id, title=title, url=url, source="feed",
        event_type="news", materiality_score=5,
    )
    db.add(event)
    db.commit()
    return event


def test_is_duplicate_by_url_or_normalized_title(db):
    company = _company(db)
    service = NewsService()
    _event(db, company, title="Apple beats expectations", url="https://x.test/a")
    assert service._is_duplicate(db, company, "anything", "https://x.test/a") is True
    # Title comparison uses the same whitespace-normalized, truncated form.
    assert service._is_duplicate(db, company, "Apple   beats  expectations", None) is True
    assert service._is_duplicate(db, company, "Different headline", "https://x.test/b") is False


def test_ingest_strips_repeated_headline_and_source_signature(db):
    """El cuerpo que repite el titular y la firma del medio no se duplica en
    el título guardado (fila «Meta (META) ... Glasses Meta (META) ...
    Glasses Simply Wall Street» vista en prod)."""
    _company(db, "META")
    service = NewsService()
    item = NewsFeedItem(
        ticker="META",
        title="Meta (META) Unveils Next-Gen Smart Glasses at Connect",
        text=(
            "Meta (META) Unveils Next-Gen Smart Glasses at Connect: "
            "the company showed new wearables during its annual event "
            "Simply Wall Street"
        ),
        source="Simply Wall Street",
        url="https://sws.example/meta-glasses",
    )
    result = service.ingest_news_items(db, [item], default_source="feed")
    assert result.created == 1
    saved = result.events[0]
    assert saved.title.count("Unveils Next-Gen Smart Glasses") == 1
    assert "Simply Wall Street" not in saved.title


def test_ingest_keeps_body_without_repetition_untouched(db):
    _company(db, "AAPL")
    service = NewsService()
    item = NewsFeedItem(
        ticker="AAPL",
        title="Apple raises buyback",
        text="The board authorized an additional program",
        source="feed",
        url="https://x.test/buyback",
    )
    result = service.ingest_news_items(db, [item], default_source="feed")
    assert result.created == 1
    assert "The board authorized an additional program" in result.events[0].title


def test_ingest_skips_duplicates_and_accounts_exactly(db):
    _company(db)
    service = NewsService()
    item = NewsFeedItem(
        ticker="AAPL", title="Apple raises buyback", text="Buyback expanded",
        source="feed", url="https://x.test/1",
    )
    first = service.ingest_news_items(db, [item])
    assert first.received == 1
    assert first.created == 1
    assert first.skipped_duplicates == 0
    second = service.ingest_news_items(db, [item, item])
    assert second.received == 2
    assert second.created == 0
    assert second.skipped_duplicates == 2



def test_ingest_preserves_source_publication_date(db):
    """Un filing de 2025 no puede aparecer con la fecha de ingesta (F73)."""
    filing_date = datetime(2025, 10, 15, 14, 30, tzinfo=UTC)
    response = NewsService().ingest_news_items(
        db,
        [NewsFeedItem(
            title="Apple files 10-K annual report",
            text="Apple 10-K",
            ticker="AAPL",
            url="https://sec.gov/x",
            published_at=filing_date,
        )],
    )
    assert response.created == 1
    event = db.query(NewsEvent).filter_by(url="https://sec.gov/x").one()
    assert event.date.replace(tzinfo=UTC) == filing_date


def test_ingest_without_source_date_falls_back_to_now(db):
    """Sin fecha de fuente, la de ingesta es el fallback legitimo."""
    response = NewsService().ingest_news_items(
        db,
        [NewsFeedItem(title="Noticia manual sin fecha fuente", text="manual", url="https://example.com/1")],
    )
    assert response.created == 1
    event = db.query(NewsEvent).filter_by(url="https://example.com/1").one()
    age = datetime.now(UTC) - event.date.replace(tzinfo=UTC)
    assert age.total_seconds() < 3600


def test_old_filing_is_never_urgent_by_recency(db):
    """Un filing de 2025 con termino critico no abre cola urgente (F217)."""
    old_date = datetime(2025, 10, 15, 14, 30, tzinfo=UTC)
    response = NewsService().ingest_news_items(
        db,
        [NewsFeedItem(
            title="Company files for bankruptcy protection in October 2025",
            text="bankruptcy filing",
            url="https://sec.gov/old",
            published_at=old_date,
        )],
    )
    assert response.created == 1
    event = db.query(NewsEvent).filter_by(url="https://sec.gov/old").one()
    assert event.materiality_score >= 7  # el score se conserva
    assert event.requires_update is False  # la urgencia, no


def test_recent_critical_news_stays_urgent(db):
    """Control: la misma noticia de hoy SI es urgente."""
    recent = datetime.now(UTC)
    response = NewsService().ingest_news_items(
        db,
        [NewsFeedItem(
            title="Company files for bankruptcy protection",
            text="bankruptcy filing",
            url="https://example.com/new",
            published_at=recent,
        )],
    )
    assert response.created == 1
    event = db.query(NewsEvent).filter_by(url="https://example.com/new").one()
    assert event.requires_update is True


def test_item_without_date_marks_ingested_fallback(db):
    """Fuente sin fecha: metadata lo declara, no se silencia (F217)."""
    response = NewsService().ingest_news_items(
        db,
        [NewsFeedItem(title="Noticia sin fecha de fuente", text="manual", url="https://example.com/2")],
    )
    assert response.created == 1
    event = db.query(NewsEvent).filter_by(url="https://example.com/2").one()
    assert event.metadata_["date_source"] == "ingested_at_fallback"


def test_ingest_does_not_duplicate_ticker_already_in_title(db):
    """F175: «COST 8-K» como título no debe guardarse como «COST COST 8-K»."""
    _company(db, ticker="COST")
    service = NewsService()
    item = NewsFeedItem(
        ticker="COST", title="COST 8-K", text="Material agreement",
        source="sec", url="https://x.test/cost-8k",
    )
    response = service.ingest_news_items(db, [item])
    assert response.created == 1
    summary = response.events[0].summary
    assert summary.startswith("COST 8-K")
    assert "COST COST" not in summary


def test_ingest_prefixes_ticker_when_title_lacks_it(db):
    _company(db, ticker="AAPL")
    service = NewsService()
    item = NewsFeedItem(
        ticker="AAPL", title="Files 10-K annual report", text="...",
        source="sec", url="https://x.test/aapl-10k",
    )
    response = service.ingest_news_items(db, [item])
    assert response.created == 1
    assert response.events[0].summary.startswith("AAPL Files 10-K")


def test_ingest_ticker_prefix_uses_word_boundary(db):
    """«COSTCO Wholesale...» no empieza por el ticker COST: sí lleva prefijo."""
    _company(db, ticker="COST")
    service = NewsService()
    item = NewsFeedItem(
        ticker="COST", title="COSTCO Wholesale files 8-K", text="...",
        source="sec", url="https://x.test/costco-8k",
    )
    response = service.ingest_news_items(db, [item])
    assert response.created == 1
    summary = response.events[0].summary
    assert summary.startswith("COST COSTCO Wholesale files 8-K")


def test_ingest_title_cut_at_word_boundary(db):
    _company(db)
    service = NewsService()
    long_text = " ".join(f"palabra{i:03d}" for i in range(60))
    item = NewsFeedItem(
        ticker="AAPL", title="Titular largo", text=long_text,
        source="feed", url="https://x.test/word-boundary",
    )
    result = service.ingest_news_items(db, [item])
    assert result.created == 1
    event = db.query(NewsEvent).filter_by(url="https://x.test/word-boundary").one()
    assert len(event.title) <= 180
    assert event.summary.startswith(event.title)
    if len(event.summary) > len(event.title):
        nxt = event.summary[len(event.title)]
        assert not (event.title[-1].isalnum() and nxt.isalnum()), "corte a media palabra"
