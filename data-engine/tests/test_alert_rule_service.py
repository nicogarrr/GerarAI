"""AlertRuleService contract tests.

Alerts drive what the user acts on: stale data must never trigger, the
cooldown must debounce repeat triggers, missing inputs evaluate honestly,
and rule creation stays idempotent.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice, NewsEvent, ResearchAlert
from app.services.alert_rule_service import AlertRuleService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _price(db: Session, company: Company, *, day: date, close: str) -> MarketPrice:
    row = MarketPrice(
        company_id=company.id, date=day, open=Decimal(close), high=Decimal(close),
        low=Decimal(close), close=Decimal(close), adj_close=Decimal(close),
        source="Finnhub",
    )
    db.add(row)
    db.commit()
    return row


def test_create_is_idempotent_and_normalizes_event_rules(db):
    company = _company(db)
    service = AlertRuleService()
    first = service.create(db, company, rule_type="news", operator="==", value=5)
    second = service.create(db, company, rule_type="news", operator="==", value=5)
    assert first.id == second.id
    # Event rules fire on existence: condition normalized to "> 0".
    assert first.condition == {"operator": ">", "value": 0}
    assert first.target == {"kind": "news_event"}
    assert first.active is True
    assert "in_app" in first.channels


def test_fresh_price_match_triggers_and_records(db):
    company = _company(db)
    _price(db, company, day=date.today(), close="210")
    service = AlertRuleService()
    rule = service.create(db, company, rule_type="price_above", operator=">", value=200)

    result = service.evaluate(db, rule)
    assert result["status"] == "triggered"
    assert result["matched"] is True
    assert result["observation"]["status"] == "fresh"
    assert rule.trigger_count == 1
    assert rule.last_triggered_at is not None
    # The alert reached the review/alert pipeline.
    assert db.query(ResearchAlert).count() == 1


def test_stale_observation_never_triggers(db):
    company = _company(db)
    _price(db, company, day=date.today() - timedelta(days=365), close="210")
    service = AlertRuleService()
    rule = service.create(db, company, rule_type="price_above", operator=">", value=200)

    result = service.evaluate(db, rule)
    assert result["status"] == "skipped_stale_observation"
    assert result["matched"] is False  # stale data forced no-match
    assert rule.trigger_count == 0
    assert db.query(ResearchAlert).count() == 0


def test_cooldown_debounces_repeat_triggers(db):
    company = _company(db)
    _price(db, company, day=date.today(), close="210")
    service = AlertRuleService()
    rule = service.create(db, company, rule_type="price_above", operator=">",
                          value=200, cooldown_seconds=3600)
    service.evaluate(db, rule)
    second = service.evaluate(db, rule)
    assert second["status"] == "evaluated"
    assert second["cooldown_active"] is True
    assert rule.trigger_count == 1
    # After the cooldown window the same condition triggers again.
    rule.last_triggered_at = datetime.now(UTC) - timedelta(seconds=3601)
    third = service.evaluate(db, rule)
    assert third["status"] == "triggered"
    assert rule.trigger_count == 2


def test_missing_data_evaluates_without_matching(db):
    company = _company(db)
    service = AlertRuleService()
    rule = service.create(db, company, rule_type="price_above", operator=">", value=200)
    result = service.evaluate(db, rule)
    assert result["status"] == "evaluated"
    assert result["matched"] is False
    assert result["observed"] is None
    assert result["observation"]["status"] == "missing"


def test_matches_numeric_and_never_on_none():
    assert AlertRuleService._matches(Decimal("210"), ">", 200) is True
    assert AlertRuleService._matches(Decimal("190"), ">", 200) is False
    assert AlertRuleService._matches(Decimal("200"), ">=", 200) is True
    assert AlertRuleService._matches("hold", "==", "hold") is True
    assert AlertRuleService._matches(None, ">", 0) is False
    assert AlertRuleService._matches(Decimal("1"), "??", 0) is False


def _news(db: Session, company: Company, *, title: str, url: str | None = "https://example.com/n") -> NewsEvent:
    event = NewsEvent(company_id=company.id, title=title, source="rss", url=url, summary="")
    db.add(event)
    db.commit()
    return event


def test_news_rule_cites_the_headline_and_stores_source(db):
    company = _company(db)
    service = AlertRuleService()
    rule = service.create(db, company, rule_type="news", operator=">", value=0)
    event = _news(db, company, title="Apple supera previsiones")

    result = service.evaluate(db, rule)

    assert result["status"] == "triggered"
    alert = db.query(ResearchAlert).one()
    assert "Apple supera previsiones" in alert.message
    assert "valor observado" not in alert.message
    assert alert.metadata_["news_event_id"] == event.id
    assert alert.metadata_["source_url"] == "https://example.com/n"


def test_news_rule_does_not_fire_without_a_verifiable_headline(db):
    company = _company(db)
    service = AlertRuleService()
    rule = service.create(db, company, rule_type="news", operator=">", value=0)
    _news(db, company, title="   ")

    result = service.evaluate(db, rule)

    assert result["status"] == "evaluated"
    assert result["matched"] is False
    assert db.query(ResearchAlert).count() == 0
