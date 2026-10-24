"""Service-level tests for tax reports, investment plan and corporate actions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Position, Transaction
from app.services.corporate_actions_service import CorporateActionService
from app.services.investment_plan_service import InvestmentPlanService
from app.services.portfolio_ledger_service import PortfolioLedgerService
from app.services.tax_report_service import TaxReportService


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def rklb(db: Session) -> Company:
    company = Company(
        ticker="RKLB",
        name="Rocket Lab",
        exchange="NASDAQ",
        currency="USD",
        sector="Industrials",
        company_type="growth",
        valuation_model="dcf",
    )
    db.add(company)
    db.commit()
    return company


def test_tax_report_fifo_realized_gains(db: Session, rklb: Company):
    ledger = PortfolioLedgerService()
    ledger.create_transaction(
        db, ticker="RKLB", action="buy", quantity=Decimal("100"), price=Decimal("20"),
        trade_date=date(2025, 6, 1), fees=Decimal("1"), currency="USD",
    )
    ledger.create_transaction(
        db, ticker="RKLB", action="buy", quantity=Decimal("50"), price=Decimal("30"),
        trade_date=date(2026, 2, 1), fees=Decimal("1"), currency="USD",
    )
    ledger.create_transaction(
        db, ticker="RKLB", action="sell", quantity=Decimal("40"), price=Decimal("35"),
        trade_date=date(2026, 5, 15), fees=Decimal("1"), currency="USD",
    )
    ledger.create_transaction(
        db, ticker="RKLB", action="dividend", quantity=Decimal("0"), price=Decimal("12.5"),
        trade_date=date(2026, 6, 10), fees=Decimal("0"), currency="USD",
    )

    report = TaxReportService().compute_report(db, 2026)
    assert report["summary"]["fiscal_year"] == 2026
    assert report["summary"]["dividend_count"] == 1
    assert report["summary"]["sell_count"] == 1
    # 40 shares sold at 35; acquisition fee prorates the old lot to 800.40.
    # Net proceeds are 1399, so the FIFO gain is 598.60.
    assert report["realized"][0]["ticker"] == "RKLB"
    assert report["realized"][0]["gain_native"] == 598.6
    assert report["dividends"][0]["dividends_native"] == 12.5


def test_tax_report_ignores_unrealized_and_no_fx(db: Session, rklb: Company):
    ledger = PortfolioLedgerService()
    ledger.create_transaction(
        db, ticker="RKLB", action="buy", quantity=Decimal("10"), price=Decimal("100"),
        trade_date=date(2026, 1, 1), fees=Decimal("0"), currency="USD",
    )
    report = TaxReportService().compute_report(db, 2026)
    assert report["summary"]["sell_count"] == 0
    assert report["summary"]["total_realized_gain_base"] == 0.0


def test_plan_metrics_and_drift(db: Session, rklb: Company):
    service = InvestmentPlanService()
    service.upsert_plan(
        db,
        monthly_contribution=Decimal("1500"),
        start_date=date(2026, 1, 1),
        horizon_years=30,
        target_allocations=[
            {"kind": "sector", "label": "Industrials", "target_pct": 40, "band_pct": 5}
        ],
    )
    service.add_contribution(db, date_=date(2026, 1, 15), amount=Decimal("1500"), currency="EUR")
    metrics = service.plan_metrics(db)
    assert metrics["plan_exists"] is True
    assert metrics["monthly_contribution"] == 1500.0
    assert metrics["actual_contributions_base"] == 1500.0

    ledger = PortfolioLedgerService()
    ledger.create_transaction(
        db, ticker="RKLB", action="buy", quantity=Decimal("10"), price=Decimal("100"),
        trade_date=date(2026, 1, 20), fees=Decimal("0"), currency="USD",
    )
    drift = service.drift_analysis(db)
    assert drift["plan_exists"] is True


def test_split_without_verified_price_applies_accounting_and_holds_valuation(db: Session, rklb: Company):
    ledger = PortfolioLedgerService()
    ledger.create_transaction(
        db, ticker="RKLB", action="buy", quantity=Decimal("50"), price=Decimal("30"),
        trade_date=date(2026, 1, 1), fees=Decimal("0"), currency="USD",
    )
    db.commit()
    CorporateActionService().create_action(
        db, ticker="RKLB", action_type="split",
        effective_date=date(2026, 7, 1), ratio=Decimal("4"), description="1:4",
    )
    position = db.scalar(select(Position).where(Position.company_id == rklb.id))
    assert position.quantity == Decimal("200") and position.average_cost == Decimal("7.5")
    assert position.valuation_hold_reason and position.market_value_base is None
    tx = db.scalar(select(Transaction).where(Transaction.company_id == rklb.id))
    assert tx.quantity == Decimal("200") and tx.price == Decimal("7.5")


def test_split_adjusts_position_and_historical_transactions(db: Session, rklb: Company):
    ledger = PortfolioLedgerService()
    ledger.create_transaction(
        db, ticker="RKLB", action="buy", quantity=Decimal("50"), price=Decimal("30"),
        trade_date=date(2026, 1, 1), fees=Decimal("0"), currency="USD",
    )
    position = db.scalar(select(Position).where(Position.company_id == rklb.id))
    assert position.quantity == Decimal("50")

    service = CorporateActionService()
    action = service.create_action(
        db,
        ticker="RKLB",
        action_type="split",
        effective_date=date(2026, 7, 1),
        ratio=Decimal("4"),
        description="1:4",
        apply_now=True,
        post_split_price=Decimal("9"),
        post_split_price_as_of=date(2026, 7, 2),
    )
    assert action.applied is True

    position = db.scalar(select(Position).where(Position.company_id == rklb.id))
    assert position.quantity == Decimal("200")
    assert position.average_cost == Decimal("7.5")

    tx = db.scalar(select(Transaction).where(Transaction.company_id == rklb.id))
    assert tx.quantity == Decimal("200")
    assert tx.price == Decimal("7.5")


def test_split_ratio_must_be_positive(db: Session, rklb: Company):
    service = CorporateActionService()
    with pytest.raises(ValueError):
        service.create_action(
            db,
            ticker="RKLB",
            action_type="split",
            effective_date=date(2026, 7, 1),
            ratio=Decimal("0"),
            description="invalid",
            apply_now=False,
        )