"""HistoricalValuationService contract tests.

Historical multiples are only meaningful point-in-time: future data must
stay out of the series, missing inputs must stay visibly missing, and every multiple must
be traceable to the stored rows that produced it.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact, MarketPrice
from app.services.historical_valuation_service import HistoricalValuationService


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


def _fact(db, company, *, metric, fiscal_year, value, quarter=None):
    fact = FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)), unit="USD",
        period=f"{fiscal_year}:FY", fiscal_year=fiscal_year, fiscal_quarter=quarter,
        source_type="SEC", is_reported=True, confidence=Decimal("0.95"),
    )
    db.add(fact)
    db.commit()
    return fact


def test_series_math_and_source_ids(db):
    company = _company(db)
    price = MarketPrice(
        company_id=company.id, date=date(2024, 12, 31),
        open=Decimal("190"), high=Decimal("200"), low=Decimal("189"),
        close=Decimal("200"), adj_close=Decimal("200"), source="Finnhub",
    )
    db.add(price)
    db.commit()
    eps = _fact(db, company, metric="eps", fiscal_year=2024, value="10")
    shares = _fact(db, company, metric="shares_diluted", fiscal_year=2024, value="100")
    fcf = _fact(db, company, metric="free_cash_flow", fiscal_year=2024, value="1000")
    revenue = _fact(db, company, metric="revenue", fiscal_year=2024, value="4000")
    _fact(db, company, metric="total_debt", fiscal_year=2024, value="300")
    _fact(db, company, metric="cash_and_equivalents", fiscal_year=2024, value="100")

    result = HistoricalValuationService().build(db, company, as_of=date(2026, 9, 23))
    assert result["ticker"] == "AAPL"
    point = next(p for p in result["series"] if p["year"] == 2024)
    # market cap 200*100=20000; EV = 20000 + 300 - 100 = 20200
    assert point["pe"] == pytest.approx(Decimal("20"))
    assert point["fcf_per_share"] == pytest.approx(Decimal("10"))
    assert point["revenue_per_share"] == pytest.approx(Decimal("40"))
    assert point["ev_to_fcf"] == pytest.approx(Decimal("20.2"))
    assert point["ev_to_revenue"] == pytest.approx(Decimal("5.05"))
    assert point["source_ids"]["market_price"] == price.id
    assert point["source_ids"]["eps"] == eps.id
    assert result["coverage"]["complete_valuation_points"] == 1
    assert result["statistics"]["pe"]["median"] == pytest.approx(Decimal("20"))


def test_future_data_is_excluded_not_raised(db):
    company = _company(db)
    db.add(
        MarketPrice(
            company_id=company.id, date=date(2026, 12, 31),
            open=Decimal("1"), high=Decimal("1"), low=Decimal("1"),
            close=Decimal("1"), adj_close=Decimal("1"), source="Finnhub",
        )
    )
    db.commit()
    _fact(db, company, metric="eps", fiscal_year=2027, value="1")
    # Revision GerarAI A2: un replay filtra lo posterior a as_of en vez de
    # abortar; ni el precio de dic-2026 ni el FY2027 entran en la serie.
    result = HistoricalValuationService().build(db, company, as_of=date(2026, 9, 23))
    assert result["series"] == []


def test_missing_inputs_stay_none_and_are_reported(db):
    company = _company(db)
    db.add(
        MarketPrice(
            company_id=company.id, date=date(2024, 12, 31),
            open=Decimal("1"), high=Decimal("1"), low=Decimal("1"),
            close=Decimal("200"), adj_close=Decimal("200"), source="Finnhub",
        )
    )
    db.commit()
    # Price only, no fundamentals: multiples are None, never fabricated.
    result = HistoricalValuationService().build(db, company, as_of=date(2026, 9, 23))
    point = result["series"][0]
    assert point["pe"] is None
    assert point["ev_to_fcf"] is None
    assert result["coverage"]["complete_valuation_points"] == 0
    assert 2024 in result["coverage"]["missing_by_metric"]["pe"]
    assert result["statistics"]["pe"]["median"] is None


def test_quarterly_facts_excluded_from_annual_series(db):
    company = _company(db)
    _fact(db, company, metric="eps", fiscal_year=2024, value="99", quarter="Q1")
    result = HistoricalValuationService().build(db, company, as_of=date(2026, 9, 23))
    # A lone quarterly fact never enters the annual series.
    assert result["series"] == []


def test_percentile_interpolates_between_points():
    service = HistoricalValuationService()
    values = [Decimal("10"), Decimal("20"), Decimal("30")]
    assert service._percentile(values, Decimal("0.5")) == Decimal("20")
    assert service._percentile(values, Decimal("0.25")) == pytest.approx(Decimal("15"))
    assert service._percentile([Decimal("7")], Decimal("0.9")) == Decimal("7")
