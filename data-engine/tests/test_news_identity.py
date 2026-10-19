"""Una noticia, un aviso: identidad por URL normalizada o titular normalizado."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, NewsEvent, ResearchAlert
from app.services.alert_rule_service import AlertRuleService
from app.services.news_identity import (
    equivalent_news_alert,
    equivalent_news_event,
    news_key,
    normalize_headline,
    normalize_url,
)
from app.services.review_alert_service import ReviewAlertService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _event(db, company, title, url):
    event = NewsEvent(company_id=company.id, title=title, source="rss", url=url, summary="")
    db.add(event)
    db.commit()
    return event


def test_normalize_url_drops_query_fragment_case_and_trailing_slash():
    a = normalize_url("HTTPS://Finance.Yahoo.com/news/x-1.html/?.tsrc=rss#top")
    b = normalize_url("https://finance.yahoo.com/news/x-1.html")
    assert a == b == "finance.yahoo.com/news/x-1.html"
    assert normalize_url("ftp://x.com/a") is None
    assert normalize_url("") is None and normalize_url(None) is None


def test_news_key_falls_back_to_normalized_headline():
    assert news_key(None, "RKLB: Worst Week Ever!") == news_key("", "rklb worst  week ever")
    assert news_key("https://a.com/x?y=1", "t").startswith("u:")
    assert news_key(None, "  ") is None


def test_equivalent_news_event_matches_url_variants_and_headline(db):
    company = _company(db)
    first = _event(db, company, "RKLB Stock Suffers Worst Week Ever", "https://finance.yahoo.com/n/1.html?.tsrc=rss")
    assert equivalent_news_event(db, company_id=company.id, url="https://finance.yahoo.com/n/1.html", title="otra").id == first.id
    assert equivalent_news_event(db, company_id=company.id, url=None, title="rklb stock suffers worst week ever!").id == first.id
    assert equivalent_news_event(db, company_id=company.id, url="https://finance.yahoo.com/n/2.html", title="distinta") is None


def test_rule_alert_is_suppressed_when_review_alert_already_covers_the_news(db):
    company = _company(db)
    service = AlertRuleService()
    rule = service.create(db, company, rule_type="news", operator=">", value=0)
    event = _event(db, company, "Iridium deal challenged", "https://example.com/n/1?utm=a")
    ReviewAlertService().emit_alert(
        db, company_id=company.id, alert_type="news_material_update", severity="high",
        title="Revisión necesaria", message="x", fingerprint_parts=["a"],
        metadata={"news_event_id": event.id},
    )
    db.commit()
    assert equivalent_news_alert(db, company_id=company.id, url="https://example.com/n/1", title=None) is not None

    result = service.evaluate(db, rule)

    assert result["status"] == "evaluated"
    assert db.query(ResearchAlert).count() == 1


def test_review_for_same_news_is_created_without_second_alert(db):
    company = _company(db)
    event = _event(db, company, "Iridium deal challenged", "https://example.com/n/1")
    svc = ReviewAlertService()
    svc.emit_alert(
        db, company_id=company.id, alert_type="tracked_news", severity="medium",
        title="t", message="m", fingerprint_parts=["tracked"],
        metadata={"news_event_id": event.id, "source_url": event.url},
    )
    db.commit()
    review = svc.create_review(
        db, review_type="news_material_update", title="Revisión necesaria", summary="s",
        company_id=company.id, news_event_id=event.id,
    )
    assert review.id is not None
    assert db.query(ResearchAlert).count() == 1
