"""Reglas de alerta ``price_change``: variación diaria honesta.

La observación ``price_change_percent`` no tenía ningún test. Compara las dos
últimas filas de MarketPrice; con cierres cotizados, un split entre ambas
sesiones se leía como un desplome (200 -> 110 tras un split 2:1 = -45 %) y
disparaba una alerta falsa de caída.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice, ResearchAlert
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
        ticker="SPLT", name="Split Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _price(db: Session, company: Company, *, day: date, close: str, adj: str | None) -> None:
    db.add(
        MarketPrice(
            company_id=company.id, date=day, open=Decimal(close), high=Decimal(close),
            low=Decimal(close), close=Decimal(close),
            adj_close=None if adj is None else Decimal(adj), source="yfinance",
        )
    )
    db.commit()


def test_split_between_sessions_is_not_a_crash(db):
    company = _company(db)
    today = date.today()
    # Split 2:1: cotizado 200 -> 110, ajustado 100 -> 110 (+10 %).
    _price(db, company, day=today - timedelta(days=1), close="200", adj="100")
    _price(db, company, day=today, close="110", adj="110")
    service = AlertRuleService()
    drop = service.create(db, company, rule_type="price_change", operator="<", value=-20)

    result = service.evaluate(db, drop)

    assert result["status"] == "evaluated"
    assert result["matched"] is False
    assert Decimal(result["observed"]) == Decimal("10")
    assert result["observation"]["basis"] == "adj_close"
    assert db.query(ResearchAlert).count() == 0


def test_real_move_on_adjusted_closes_triggers(db):
    company = _company(db)
    today = date.today()
    _price(db, company, day=today - timedelta(days=1), close="200", adj="100")
    _price(db, company, day=today, close="110", adj="110")
    service = AlertRuleService()
    rise = service.create(db, company, rule_type="price_change", operator=">", value=5)

    result = service.evaluate(db, rise)

    assert result["status"] == "triggered"
    assert db.query(ResearchAlert).count() == 1


def test_without_adjusted_close_uses_quoted_close(db):
    # Filas sin ajuste (FMP, intradía): se conserva el cálculo sobre el cierre.
    company = _company(db)
    today = date.today()
    _price(db, company, day=today - timedelta(days=1), close="100", adj=None)
    _price(db, company, day=today, close="90", adj="90")
    service = AlertRuleService()
    rule = service.create(db, company, rule_type="price_change", operator="<=", value=-10)

    result = service.evaluate(db, rule)

    assert result["observation"]["basis"] == "close"
    assert Decimal(result["observed"]) == Decimal("-10")
    assert result["status"] == "triggered"


def test_single_price_is_missing_not_zero(db):
    company = _company(db)
    _price(db, company, day=date.today(), close="100", adj="100")
    service = AlertRuleService()
    rule = service.create(db, company, rule_type="price_change", operator="<", value=1)

    result = service.evaluate(db, rule)

    assert result["observed"] is None
    assert result["observation"]["status"] == "missing_two_prices"
    assert result["matched"] is False


def test_zero_previous_close_never_divides(db):
    company = _company(db)
    today = date.today()
    _price(db, company, day=today - timedelta(days=1), close="0", adj=None)
    _price(db, company, day=today, close="5", adj=None)
    service = AlertRuleService()
    rule = service.create(db, company, rule_type="price_change", operator=">", value=1)

    result = service.evaluate(db, rule)

    assert result["observation"]["status"] == "missing_two_prices"
    assert result["matched"] is False


def test_stale_price_change_never_triggers(db):
    company = _company(db)
    old = date.today() - timedelta(days=400)
    _price(db, company, day=old - timedelta(days=1), close="100", adj="100")
    _price(db, company, day=old, close="50", adj="50")
    service = AlertRuleService()
    rule = service.create(db, company, rule_type="price_change", operator="<", value=-10)

    result = service.evaluate(db, rule)

    assert result["status"] == "skipped_stale_observation"
    assert result["matched"] is False
    assert db.query(ResearchAlert).count() == 0
