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


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "nan", "NaN", "Infinity", "-inf"])
def test_create_rejects_non_finite_threshold(db, bad):
    company = _company(db)
    with pytest.raises(ValueError, match="finite"):
        AlertRuleService().create(db, company, rule_type="price_above", operator=">", value=bad)
    from app.models.entities import AlertRule

    assert db.query(AlertRule).count() == 0


@pytest.mark.parametrize("op", [">", "<", ">=", "<=", "==", "!="])
@pytest.mark.parametrize("bad", ["nan", "NaN", "inf", "-Infinity"])
def test_matches_non_finite_is_false_never_raises(op, bad):
    assert AlertRuleService._matches(Decimal("210"), op, bad) is False
    assert AlertRuleService._matches(Decimal("NaN"), op, 200) is False


def test_legacy_nan_rule_does_not_abort_the_evaluation_pass(db):
    from app.models.entities import AlertRule

    company = _company(db)
    _price(db, company, day=date.today(), close="210")
    service = AlertRuleService()
    good = service.create(db, company, rule_type="price_above", operator=">", value=200)
    legacy = AlertRule(
        company_id=company.id, name="AAPL: legacy nan", rule_type="price_above",
        condition={"operator": ">", "value": "nan"}, target={"kind": "market_price"},
        severity="medium", channels=["in_app"], active=True,
    )
    db.add(legacy)
    db.commit()
    results = service.evaluate_all(db)
    by_id = {r["rule_id"]: r for r in results}
    assert by_id[good.id]["status"] == "triggered"
    assert by_id[legacy.id]["matched"] is False


def test_manual_alert_payload_rejects_non_finite_value():
    from pydantic import ValidationError

    from app.api.routes.alerts import ManualAlertCreate

    for bad in (float("nan"), float("inf"), "nan", "-Infinity"):
        with pytest.raises(ValidationError):
            ManualAlertCreate(ticker="AAPL", alert_type="price_above", operator=">", value=bad)
    assert ManualAlertCreate(ticker="AAPL", alert_type="price_above", operator=">", value="1.5").value == "1.5"
    assert ManualAlertCreate(ticker="AAPL", alert_type="price_above", operator=">", value=200).value == 200


def test_legacy_three_day_setting_cannot_mark_yesterday_price_fresh(db, monkeypatch):
    from types import SimpleNamespace

    from app.services import alert_rule_service as module

    company = _company(db)
    _price(db, company, day=date.today() - timedelta(days=1), close="210")
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(market_price_max_age_days=3))
    rule = module.AlertRule(company_id=company.id, target={"kind": "market_price"})
    _, observation = AlertRuleService()._observe(db, rule)
    assert observation["status"] == "stale"


def test_max_age_zero_keeps_today_price_fresh(db, monkeypatch):
    """MARKET_PRICE_MAX_AGE_DAYS=0 significa «solo hoy», no «nunca actual»."""
    from types import SimpleNamespace

    from app.services import alert_rule_service as module

    company = _company(db)
    _price(db, company, day=date.today(), close="210")
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(market_price_max_age_days=0))
    rule = module.AlertRule(company_id=company.id, target={"kind": "market_price"})
    _, observation = AlertRuleService()._observe(db, rule)
    assert observation["status"] == "fresh"



def _london_price(db: Session, company: Company, *, day: date, close: str, unit: str) -> None:
    db.add(MarketPrice(
        company_id=company.id, date=day, open=Decimal(close), high=Decimal(close), low=Decimal(close),
        close=Decimal(close), adj_close=Decimal(close), source="yahoo_finance", quote_currency=unit,
    ))
    db.commit()


def _london_company(db: Session) -> Company:
    company = Company(
        ticker="VOD.L", name="Vodafone", exchange="LSE", currency="GBp",
        sector="Telecom", industry="Telecom", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_price_change_compares_pence_and_pounds_in_the_same_unit(db):
    """70 GBp ayer y 0,71 GBP hoy es +1,43 %, no -99 %."""
    from app.services import alert_rule_service as module

    company = _london_company(db)
    _london_price(db, company, day=date.today() - timedelta(days=1), close="70", unit="GBp")
    _london_price(db, company, day=date.today(), close="0.71", unit="GBP")
    rule = module.AlertRule(company_id=company.id, target={"kind": "price_change_percent"})
    change, observation = AlertRuleService()._observe(db, rule)
    assert observation["status"] == "fresh"
    assert change == pytest.approx(Decimal("1.428571"), abs=Decimal("0.0001"))


def test_price_change_between_different_moneys_is_not_a_move(db):
    from app.services import alert_rule_service as module

    company = _london_company(db)
    _london_price(db, company, day=date.today() - timedelta(days=1), close="70", unit="GBp")
    _london_price(db, company, day=date.today(), close="0.90", unit="USD")
    rule = module.AlertRule(company_id=company.id, target={"kind": "price_change_percent"})
    change, observation = AlertRuleService()._observe(db, rule)
    assert change is None and observation["status"] == "mixed_units"
