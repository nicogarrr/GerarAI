"""Umbrales no numéricos en alertas de precio/cambio (bug alerts-1).

Antes se aceptaba ``value="abc"`` (o «1,234») en una alerta ``price_above``:
la regla quedaba activa en /alerts pero ``_matches`` no puede ordenar texto, así
que nunca se disparaba y el usuario no recibía ningún aviso.
"""

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.alerts import ManualAlertCreate
from app.models.entities import Base, Company
from app.services.alert_rule_service import AlertRuleService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db) -> Company:
    company = Company(
        ticker="AAPL", name="Apple Inc", exchange="NASDAQ", currency="USD", sector="Technology",
        industry="Hardware", company_type="research_candidate", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


@pytest.mark.parametrize("alert_type", ["price_above", "price_below", "price_change"])
@pytest.mark.parametrize("bad", ["abc", "1,234", "", "  ", "200€", "<script>"])
def test_payload_rejects_non_numeric_threshold_for_numeric_alerts(alert_type, bad):
    with pytest.raises(ValidationError):
        ManualAlertCreate(ticker="AAPL", alert_type=alert_type, operator=">", value=bad)


@pytest.mark.parametrize("good", [200, 200.5, "200", " 199.99 ", "-5"])
def test_payload_accepts_numeric_threshold(good):
    payload = ManualAlertCreate(ticker="AAPL", alert_type="price_change", operator="<", value=good)
    assert payload.value == good


@pytest.mark.parametrize("alert_type", ["news", "earnings"])
def test_valueless_alerts_still_accept_any_value(alert_type):
    payload = ManualAlertCreate(ticker="AAPL", alert_type=alert_type, operator=">", value="")
    assert payload.alert_type == alert_type


@pytest.mark.parametrize("rule_type", ["price_above", "price_below", "price_change"])
def test_service_rejects_non_numeric_threshold(db, rule_type):
    company = _company(db)
    with pytest.raises(ValueError):
        AlertRuleService().create(db, company, rule_type=rule_type, operator=">", value="abc")


def test_service_keeps_numeric_string_threshold(db):
    company = _company(db)
    rule = AlertRuleService().create(db, company, rule_type="price_above", operator=">", value="200")
    assert rule.condition == {"operator": ">", "value": "200"}
    assert AlertRuleService._matches(201, ">", rule.condition["value"]) is True
