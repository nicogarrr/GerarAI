"""Procedencia del connector GDELT: se graba en la creación (misma
transacción); un duplicado URL previamente ingerido vía RSS NO se reetiqueta
como GDELT."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, NewsEvent, Tenant
from app.schemas import NewsFeedItem
from app.services.news_service import NewsService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        tenant = Tenant(external_id="t", name="T", metadata_={}, status="active")
        session.add(tenant)
        session.flush()
        session.add(Company(ticker="ACME", name="Acme", exchange="NASDAQ", currency="USD",
                            company_type="holding", valuation_model="unassigned"))
        session.commit()
        session.info["tenant_id"] = tenant.id
        yield session
    engine.dispose()


def test_connector_written_at_creation(db):
    resp = NewsService().ingest_news_items(
        db,
        [NewsFeedItem(title="GDELT item", text=None, ticker="ACME",
                      url="https://x.example/a", source="gdelt",
                      published_at=datetime(2026, 9, 24, 8, tzinfo=UTC))],
        default_source="gdelt",
        connector="gdelt",
    )
    db.commit()
    assert resp.created == 1
    event = db.scalars(select(NewsEvent)).one()
    assert (event.metadata_ or {}).get("connector") == "gdelt"


def test_duplicate_rss_url_is_not_relabeled_gdelt(db):
    first = NewsService().ingest_news_items(
        db,
        [NewsFeedItem(title="RSS item", text=None, ticker="ACME",
                      url="https://x.example/dup", source="rss",
                      published_at=datetime(2026, 9, 24, 8, tzinfo=UTC))],
        default_source="feed",
    )
    db.commit()
    assert first.created == 1
    second = NewsService().ingest_news_items(
        db,
        [NewsFeedItem(title="Same URL via GDELT", text=None, ticker="ACME",
                      url="https://x.example/dup", source="gdelt",
                      published_at=datetime(2026, 9, 24, 9, tzinfo=UTC))],
        default_source="gdelt",
        connector="gdelt",
    )
    db.commit()
    assert second.created == 0
    assert second.skipped_duplicates == 1
    event = db.scalars(select(NewsEvent)).one()
    assert (event.metadata_ or {}).get("connector") != "gdelt"


def test_competitor_news_under_feed_ticker_is_not_linked(db):
    db.add(Company(ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ", currency="USD",
                   company_type="holding", valuation_model="unassigned"))
    db.commit()
    resp = NewsService().ingest_news_items(
        db,
        [
            NewsFeedItem(title="Rocket Lab wins new Neutron launch contract", text=None,
                         ticker="ASTS", url="https://x.example/rklb", source="rss",
                         published_at=datetime(2026, 9, 24, 8, tzinfo=UTC)),
            NewsFeedItem(title="AST SpaceMobile and Rocket Lab sign launch deal", text=None,
                         ticker="ASTS", url="https://x.example/both", source="rss",
                         published_at=datetime(2026, 9, 24, 8, tzinfo=UTC)),
        ],
        default_source="feed",
    )
    db.commit()
    assert resp.created == 1
    assert db.scalars(select(NewsEvent)).one().url == "https://x.example/both"
