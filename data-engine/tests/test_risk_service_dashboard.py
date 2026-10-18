"""RiskService.dashboard contract tests.

The portfolio risk snapshot must convert everything to base currency
point-in-time, exclude - never guess - rows without an FX rate, and say
so through status, provenance and the missing_fx ledger.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, CashBalance, Company, Portfolio, Position
from app.services.risk_service import RiskService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Co", exchange="XETRA", currency="EUR",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_base_currency_position_and_cash_valued_without_fx(db):
    company = _company(db, "SAN")
    db.add(
        Position(
            company_id=company.id, quantity=Decimal("10"), market_price=Decimal("100"),
            currency="EUR", market_value_native=Decimal("1000"), market_value_base=None,
            as_of=date(2026, 9, 20),
        )
    )
    db.add(CashBalance(currency="EUR", balance=Decimal("500"), as_of=date(2026, 9, 21)))
    db.commit()

    result = RiskService().dashboard(db)
    assert result["status"] == "ok"
    assert result["base_currency"] == "EUR"
    assert result["missing_fx"] == []
    assert result["cash_native"] == {"EUR": 500.0}
    assert result["total_value"] == pytest.approx(1500.0)
    assert result["data_as_of"] == "2026-09-20"
    assert result["provenance"]["coverage"] == "ok"
    assert result["trace"]["excluded_for_missing_fx"] == 0


def test_position_without_base_value_excluded_and_reported(db):
    company = _company(db, "AAPL")
    db.add(
        Position(
            company_id=company.id, quantity=Decimal("5"), market_price=Decimal("200"),
            currency="USD", market_value=Decimal("1000"), market_value_base=None,
            as_of=date(2026, 9, 20),
        )
    )
    db.commit()

    result = RiskService().dashboard(db)
    assert result["status"] == "incomplete_fx"
    assert result["missing_fx"] == [
        {
            "kind": "position",
            "ticker": "AAPL",
            "quote_currency": "USD",
            "base_currency": "EUR",
            "as_of": "2026-09-20",
        }
    ]
    assert result["total_value"] == 0.0  # excluded, never guessed
    assert result["provenance"]["coverage"] == "partial"
    assert result["trace"]["excluded_for_missing_fx"] == 1
    assert result["trace"]["fx_policy"].startswith("quote amount multiplied by latest rate on or before")


def test_cash_without_fx_rate_excluded_and_reported(db):
    db.add(CashBalance(currency="USD", balance=Decimal("800"), as_of=date(2026, 9, 20)))
    db.add(CashBalance(currency="EUR", balance=Decimal("200"), as_of=date(2026, 9, 20)))
    db.commit()

    result = RiskService().dashboard(db)
    assert result["status"] == "incomplete_fx"
    cash_missing = [m for m in result["missing_fx"] if m["kind"] == "cash"]
    assert cash_missing == [
        {
            "kind": "cash",
            "quote_currency": "USD",
            "base_currency": "EUR",
            "as_of": "2026-09-20",
        }
    ]
    # USD cash kept out of the base total; EUR cash counted at par.
    assert result["cash_native"] == {"USD": 800.0, "EUR": 200.0}
    assert result["total_value"] == pytest.approx(200.0)


def test_margin_breakdown_separates_positive_cash_and_debt(db):
    from app.models.entities import FXRate
    company = _company(db, "TEST")
    day = date(2026, 9, 20)
    db.add(Position(company_id=company.id, quantity=Decimal("10"),
                    market_value_base=Decimal("18000"), currency="EUR", as_of=day))
    db.add(CashBalance(currency="EUR", balance=Decimal("8000"), as_of=day))
    db.add(CashBalance(currency="USD", balance=Decimal("-20000"), as_of=day))
    db.add(FXRate(base_currency="EUR", quote_currency="USD", rate=Decimal("0.9"),
                  rate_date=day, source="synthetic"))
    db.commit()
    result = RiskService().dashboard(db)
    assert result["cash_assets_base"] == 8000
    assert result["margin_debt_base"] == 18000
    assert result["cash"] == {"EUR": -10000}
    assert result["equity_value"] == 18000
    assert result["total_value"] == 8000
    assert result["total_value"] == (result["equity_value"]
        + result["cash_assets_base"] - result["margin_debt_base"])


def test_margin_breakdown_does_not_guess_unconvertible_debt(db):
    db.add(CashBalance(currency="USD", balance=Decimal("-20000"), as_of=date(2026, 9, 20)))
    db.commit()
    result = RiskService().dashboard(db)
    assert result["cash_assets_base"] == result["margin_debt_base"] == 0
    assert result["status"] == "incomplete_fx"
    assert result["missing_fx"][0]["kind"] == "cash"


def test_dashboard_reports_fx_rate_and_date_used_per_scope(db):
    from app.models.entities import FXRate

    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    company = _company(db, "AAPL")
    db.add(
        Position(
            company_id=company.id, quantity=Decimal("5"), market_price=Decimal("200"),
            currency="USD", market_value=Decimal("1000"), market_value_native=Decimal("1000"),
            market_value_base=Decimal("888.7"), fx_rate=Decimal("0.8887"),
            as_of=date(2026, 10, 16),
        )
    )
    db.add(CashBalance(currency="USD", balance=Decimal("3200"), as_of=date(2026, 9, 25)))
    db.add(FXRate(base_currency="EUR", quote_currency="USD", rate=Decimal("0.8769"),
                  rate_date=date(2026, 9, 25), source="test"))
    db.commit()

    result = RiskService().dashboard(db)
    assert result["fx_rates"] == [
        {"scope": "cash", "currency": "USD", "rate": 0.8769, "as_of": "2026-09-25"},
        {"scope": "positions", "currency": "USD", "rate": 0.8887, "as_of": "2026-10-16"},
    ]
    assert result["cash_as_of"] == "2026-09-25"
    assert result["valuation_dates_differ"] is True
