"""Benchmark comparison tests: portfolio vs SPY."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice
from app.services.portfolio_intelligence_service import PortfolioIntelligenceService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _spy(db: Session) -> Company:
    company = Company(
        ticker="SPY",
        name="SPDR S&P 500",
        exchange="NYSEARCA",
        currency="USD",
        sector="ETF",
        industry="ETF",
        company_type="benchmark",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _flat_prices(db: Session, company: Company, days: int, daily: float) -> None:
    # Geometric series at a constant daily return.
    price = 100.0
    start = date(2026, 1, 1)
    for i in range(days):
        price *= 1 + daily
        db.add(
            MarketPrice(
                company_id=company.id,
                date=start + timedelta(days=i),
                close=Decimal(str(round(price, 6))),
                adj_close=Decimal(str(round(price, 6))),
                source="test",
            )
        )
    db.commit()


def test_missing_benchmark_is_honest(db):
    result = PortfolioIntelligenceService()._benchmark_comparison(
        db, {date(2026, 1, 1): 0.01}, date(2025, 1, 1)
    )
    assert result["status"] == "missing_benchmark"
    assert result["alpha_annualized"] is None


def test_insufficient_overlap_is_honest(db):
    _spy(db)
    result = PortfolioIntelligenceService()._benchmark_comparison(
        db, {date(2026, 1, 1) + timedelta(days=i): 0.001 for i in range(5)}, date(2025, 1, 1)
    )
    assert result["status"] == "insufficient_overlap"
    assert result["observations"] == 0


def test_alpha_and_information_ratio_math(db):
    company = _spy(db)
    days = 60
    start = date(2026, 1, 1)
    _flat_prices(db, company, days + 1, 0.001)  # benchmark: +0.1%/day
    # Portfolio: same dates, +0.2%/day => positive alpha.
    portfolio_returns = {start + timedelta(days=i): 0.002 for i in range(days)}
    result = PortfolioIntelligenceService()._benchmark_comparison(
        db, portfolio_returns, date(2025, 1, 1)
    )
    assert result["status"] == "calculated"
    # N+1 prices give N returns keyed by the later date; overlap is days - 1.
    assert result["observations"] == days - 1
    assert result["benchmark_annualized"] == pytest.approx(1.001**252 - 1, rel=1e-6)
    assert result["portfolio_annualized"] == pytest.approx(1.002**252 - 1, rel=1e-6)
    assert result["alpha_annualized"] > 0
    # Constant active return => zero tracking error => information ratio null, not crash.
    assert result["tracking_error"] == pytest.approx(0.0, abs=1e-6)
    assert result["information_ratio"] is None


def test_live_spy_series_is_used_without_master_row(db, monkeypatch):
    from types import SimpleNamespace

    from app.services import portfolio_intelligence_service as svc

    start = date(2026, 1, 1)
    live = [SimpleNamespace(date=start + timedelta(days=i), adj_close=Decimal(str(100 * 1.001 ** i)))
            for i in range(61)]
    monkeypatch.setattr(svc, "_live_benchmark_prices", lambda cutoff: live)
    portfolio = {start + timedelta(days=i): 0.002 for i in range(1, 61)}
    result = PortfolioIntelligenceService()._benchmark_comparison(db, portfolio, date(2025, 1, 1))
    assert result["status"] == "calculated"
    assert result["observations"] == 60
    assert result["alpha_annualized"] is not None
    assert db.scalar(__import__("sqlalchemy").select(Company).where(Company.ticker == "SPY")) is None
