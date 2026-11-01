from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, NewsEvent, Position, ResearchAlert, Tenant, WatchItem
from app.services.tracked_news_alerts import evaluate

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def _setup(db):
    t1 = Tenant(external_id="tracked-1", name="One", status="active", metadata_={})
    t2 = Tenant(external_id="tracked-2", name="Two", status="active", metadata_={})
    db.add_all((t1, t2))
    db.flush()
    a = Company(ticker="ASTS", name="AST", exchange="NASDAQ", currency="USD",
                company_type="holding", valuation_model="unassigned")
    b = Company(ticker="WATCH", name="Watch", exchange="NASDAQ", currency="USD",
                company_type="holding", valuation_model="unassigned")
    db.add_all((a, b))
    db.flush()
    db.add(Position(tenant_id=t1.id, company_id=a.id, quantity=Decimal("1")))
    db.add(WatchItem(tenant_id=t1.id, symbol="WATCH"))
    db.add(WatchItem(tenant_id=t2.id, symbol="ASTS"))
    db.commit()
    return t1, t2, a, b


def _news(db, tenant, company, title, url, *, published=NOW - timedelta(hours=2), metadata=None):
    row = NewsEvent(tenant_id=tenant.id, company_id=company.id, title=title, source="publisher.example",
                    url=url, date=published, metadata_=metadata if metadata is not None else {"date_source": "source", "connector": "rss", "source_headline": title})
    db.add(row)
    db.commit()
    return row


def test_in_app_held_and_watchlist_with_citation_and_dedup(db):
    t1, t2, a, b = _setup(db)
    _news(db, t1, a, "ASTS ITU filing submitted", "https://publisher.example/asts")
    _news(db, t1, b, "WATCH earnings report", "https://publisher.example/watch")
    _news(db, t2, a, "ASTS acquisition report", "https://publisher.example/other")
    db.info["tenant_id"] = t1.id
    result = evaluate(db, now=NOW)
    assert result["created"] == 2
    alerts = db.scalars(select(ResearchAlert).order_by(ResearchAlert.id)).all()
    assert len(alerts) == 2
    assert all(row.channels == ["in_app"] and row.alert_type == "tracked_news" for row in alerts)
    assert {row.metadata_["matching"][0] for row in alerts} == {"cartera", "watchlist"}
    assert {row.metadata_["source_url"] for row in alerts} == {
        "https://publisher.example/asts", "https://publisher.example/watch"}
    assert evaluate(db, now=NOW)["created"] == 0
    db.info["tenant_id"] = t2.id
    assert evaluate(db, now=NOW)["created"] == 1
    assert len(db.scalars(select(ResearchAlert)).all()) == 1


def test_no_unknown_date_url_or_untracked_and_cooldown(db):
    t1, _, a, b = _setup(db)
    _news(db, t1, a, "ASTS ITU filing submitted", "https://publisher.example/asts")
    _news(db, t1, a, "ASTS results", "https://publisher.example/second")
    _news(db, t1, a, "ASTS filing", "javascript:alert(1)")
    _news(db, t1, b, "WATCH filing", "https://publisher.example/fallback",
          metadata={"date_source": "ingested_at_fallback"})
    _news(db, t1, a, "ASTS filing", "https://publisher.example/old", published=NOW-timedelta(days=5))
    c = Company(ticker="OTHER", name="Other", exchange="NASDAQ", currency="USD",
                company_type="holding", valuation_model="unassigned")
    db.add(c)
    db.commit()
    _news(db, t1, c, "OTHER filing", "https://publisher.example/untracked")
    db.info["tenant_id"] = t1.id
    result = evaluate(db, now=NOW)
    assert result["created"] == 1
    assert result["cooldown_skips"] == 1
    assert len(db.scalars(select(ResearchAlert)).all()) == 1
    # A previously suppressed source may not burst out when the cooldown expires.
    assert evaluate(db, now=NOW + timedelta(hours=7))["created"] == 0


def test_no_tenant_context_fails_closed(db):
    with pytest.raises(ValueError):
        evaluate(db, now=NOW)


def test_gdelt_first_seen_is_not_claimed_as_publication_date(db):
    tenant, _, company, _ = _setup(db)
    _news(db, tenant, company, "ASTS ITU filing", "https://publisher.example/itu",
          metadata={"connector": "gdelt", "date_source": "source", "source_headline": "ASTS ITU filing"})
    db.info["tenant_id"] = tenant.id
    assert evaluate(db, now=NOW)["created"] == 1
    alert = db.scalar(select(ResearchAlert))
    assert "detectada por GDELT" in alert.message
    assert "publicó el" not in alert.message
    assert alert.metadata_["date_source"] == "gdelt_first_seen"


def test_manual_or_unattributed_news_does_not_auto_alert(db):
    tenant, _, company, _ = _setup(db)
    _news(db, tenant, company, "ASTS ITU filing", "https://publisher.example/manual",
          metadata={"date_source": "source"})
    db.info["tenant_id"] = tenant.id
    assert evaluate(db, now=NOW)["created"] == 0
    assert db.scalar(select(ResearchAlert)) is None


def test_500_ineligible_articles_do_not_hide_recent_real_headline(db):
    tenant, _, company, _ = _setup(db)
    db.info["tenant_id"] = tenant.id
    db.add_all([
        NewsEvent(tenant_id=tenant.id, company_id=company.id, title="ASTS filing from snippet",
                  source="publisher.example", url=f"https://publisher.example/boring-{i}",
                  date=NOW-timedelta(hours=40)+timedelta(seconds=i),
                  metadata_={"date_source": "source", "connector": "rss", "source_headline": "Company update"})
        for i in range(525)
    ])
    db.add(NewsEvent(tenant_id=tenant.id, company_id=company.id,
                     title="ASTS filing ITU from title and summary", source="publisher.example",
                     url="https://publisher.example/actual-itu", date=NOW-timedelta(hours=1),
                     metadata_={"date_source": "gdelt_first_seen", "connector": "gdelt",
                                "source_headline": "ASTS ITU filing submitted"}))
    db.commit()
    result = evaluate(db, now=NOW, limit=100)
    assert result["created"] == 1
    alert = db.scalar(select(ResearchAlert))
    assert "ASTS ITU filing submitted" in alert.title
    assert alert.metadata_["source_headline"] == "ASTS ITU filing submitted"


def test_eligible_snippet_cannot_promote_innocuous_source_headline(db):
    tenant, _, company, _ = _setup(db)
    db.info["tenant_id"] = tenant.id
    db.add(NewsEvent(tenant_id=tenant.id, company_id=company.id,
                     title="ASTS update: filing ITU in snippet", source="publisher.example",
                     url="https://publisher.example/summary-only", date=NOW-timedelta(hours=1),
                     metadata_={"date_source": "gdelt_first_seen", "connector": "gdelt",
                                "source_headline": "ASTS company update"}))
    db.commit()
    assert evaluate(db, now=NOW)["created"] == 0


def test_actual_feed_ingestion_preserves_headline_before_alert_gate(db, monkeypatch):
    from app.schemas import NewsIngestResponse
    from app.services.connectors.base import ConnectorItem, ConnectorResult
    from app.services.feed_ingestion_service import FeedIngestionService
    from app.services.news_service import NewsService

    tenant, _, company, _ = _setup(db)
    db.info["tenant_id"] = tenant.id

    def ingest_stub(self, session, items, default_source="feed", connector=None,
                    date_source_label=None, news_lane=None, macro_theme=None,
                    detect_company=True, llm_deadline=None):
        # Exercise actual FeedIngestionService mapping and creation-time
        # provenance/headline enrichment; isolate expensive thesis/LLM side
        # effects in NewsService.
        for item in items:
            metadata = {"date_source": (date_source_label or "source") if item.published_at
                        else "ingested_at_fallback"}
            if connector:
                metadata["connector"] = connector
            if item.title:
                metadata["source_headline"] = item.title[:500]
            if news_lane:
                metadata["news_lane"] = news_lane
            if macro_theme:
                metadata["macro_theme"] = macro_theme
            session.add(NewsEvent(tenant_id=tenant.id, company_id=company.id,
                                  title=f"{company.ticker} {item.title} {item.text}",
                                  source=item.source, url=item.url, date=item.published_at,
                                  metadata_=metadata))
        session.commit()
        return NewsIngestResponse(status="ingested", received=len(items), created=len(items),
                                  skipped_duplicates=0, requires_update=0, events=[])

    monkeypatch.setattr(NewsService, "ingest_news_items", ingest_stub)
    result = ConnectorResult(source="gdelt", items=[
        ConnectorItem(source="publisher.example", title="Company update", summary="New ITU filing",
                      url="https://publisher.example/no", ticker="ASTS", published_at=NOW-timedelta(hours=2)),
        ConnectorItem(source="publisher.example", title="ASTS ITU filing submitted", summary="Company update",
                      url="https://publisher.example/yes", ticker="ASTS", published_at=NOW-timedelta(hours=1)),
    ])
    FeedIngestionService().ingest_news_result(db, result, ticker="ASTS")
    rows = db.scalars(select(NewsEvent).order_by(NewsEvent.id)).all()
    assert [r.metadata_["source_headline"] for r in rows] == ["Company update", "ASTS ITU filing submitted"]
    assert evaluate(db, now=NOW)["created"] == 1
    alert = db.scalar(select(ResearchAlert))
    assert alert.metadata_["source_url"] == "https://publisher.example/yes"
    assert "Company update" not in alert.title


def test_headline_of_other_company_under_tracked_ticker_makes_no_alert(db):
    t1, _, a, _ = _setup(db)
    _news(db, t1, a, "Novo Nordisk filing shows new obesity data", "https://publisher.example/novo")
    db.info["tenant_id"] = t1.id
    assert evaluate(db, now=NOW)["created"] == 0


def test_alert_in_english_for_user_with_english_saved(db, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        t1, t2, a, b = _setup(db)
        t1.metadata_ = {"language": "en"}
        db.commit()
        _news(db, t1, a, "ASTS ITU filing submitted", "https://publisher.example/asts")
        _news(db, t2, a, "ASTS acquisition report", "https://publisher.example/other")
        db.info["tenant_id"] = t1.id
        evaluate(db, now=NOW)
        english = db.scalars(select(ResearchAlert)).one()
        db.info["tenant_id"] = t2.id
        evaluate(db, now=NOW)
        spanish = db.scalars(select(ResearchAlert)).one()
        assert english.title == "News about ASTS: ASTS ITU filing submitted"
        assert english.message == (
            "Article from publisher.example, dated 2026-09-27 by publisher.example: ASTS ITU filing submitted. "
            "Check the source; the GDELT date is not the publication date and the headline alone does not confirm the facts."
        )
        assert english.metadata_["language"] == "en"
        assert spanish.title == "Noticia sobre ASTS: ASTS acquisition report"
        assert spanish.message.startswith("Artículo de publisher.example, fechada el 2026-09-27 por publisher.example")
        assert "language" not in spanish.metadata_
    finally:
        monkeypatch.delenv("I18N_GENERATION_ENABLED")
        get_settings.cache_clear()
