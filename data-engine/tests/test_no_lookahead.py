"""Hermetic tests: point-in-time guard against look-ahead bias.

Unit-cover the guard helpers and prove HistoricalValuationService.build()
leaves out data dated after its ``as_of`` cutoff (it filters, it does not
raise: revision GerarAI A2) while accepting in-window data.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, FinancialFact, MarketPrice
from app.services.historical_valuation_service import HistoricalValuationService
from app.valuation.point_in_time import (
    LookaheadError,
    assert_fiscal_year_no_lookahead,
    assert_no_lookahead,
)

AS_OF = date(2024, 6, 30)


def test_assert_no_lookahead_accepts_past_equal_and_unknown():
    assert_no_lookahead(as_of=AS_OF, data_date=date(2024, 6, 30), label="x")
    assert_no_lookahead(as_of=AS_OF, data_date=date(2020, 1, 1), label="x")
    assert_no_lookahead(as_of=AS_OF, data_date=None, label="x")


def test_assert_no_lookahead_rejects_future_date():
    with pytest.raises(LookaheadError, match="after as_of"):
        assert_no_lookahead(as_of=AS_OF, data_date=date(2024, 7, 1), label="price AAA")


def test_assert_fiscal_year_no_lookahead():
    assert_fiscal_year_no_lookahead(as_of=AS_OF, fiscal_year=2024, label="x")
    assert_fiscal_year_no_lookahead(as_of=AS_OF, fiscal_year=None, label="x")
    with pytest.raises(LookaheadError, match="fiscal year 2025"):
        assert_fiscal_year_no_lookahead(as_of=AS_OF, fiscal_year=2025, label="revenue AAA")


def _db_with(as_of: date, price_date: date, fact_year: int) -> tuple[Session, Company]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    company = Company(
        ticker="PIT",
        name="Point In Time Co",
        exchange="TEST",
        currency="USD",
        sector="Test",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    db.add(
        MarketPrice(
            company_id=company.id,
            date=price_date,
            close=Decimal("100"),
            adj_close=Decimal("100"),
            source="test",
        )
    )
    for metric in ("eps", "shares_diluted"):
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=metric,
                value=Decimal("10"),
                unit="USD",
                period=f"FY{fact_year}",
                fiscal_year=fact_year,
                fiscal_quarter="FY",
                source_type="test",
                confidence=Decimal("0.9"),
            )
        )
    db.commit()
    return db, company


def test_build_excludes_future_price():
    db, company = _db_with(AS_OF, price_date=date(2024, 7, 15), fact_year=2023)
    try:
        result = HistoricalValuationService().build(db, company, as_of=AS_OF)
    finally:
        db.close()
    assert all(point["price"] is None for point in result["series"])
    assert result["coverage"]["missing_by_metric"]["price"] == [2023]


def test_build_excludes_future_fundamental():
    db, company = _db_with(AS_OF, price_date=date(2024, 5, 1), fact_year=2025)
    try:
        result = HistoricalValuationService().build(db, company, as_of=AS_OF)
    finally:
        db.close()
    assert [point["year"] for point in result["series"]] == [2024]
    assert result["series"][0]["eps"] is None


def test_build_accepts_in_window_data():
    db, company = _db_with(AS_OF, price_date=date(2024, 5, 1), fact_year=2024)
    try:
        result = HistoricalValuationService().build(db, company, as_of=AS_OF)
    finally:
        db.close()
    years = [point["year"] for point in result["series"]]
    assert 2024 in years


def test_build_defaults_as_of_to_today_without_future_data():
    db, company = _db_with(AS_OF, price_date=date(2020, 5, 1), fact_year=2020)
    try:
        result = HistoricalValuationService().build(db, company)
    finally:
        db.close()
    assert result["ticker"] == "PIT"
