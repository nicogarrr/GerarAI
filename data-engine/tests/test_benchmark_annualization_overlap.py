"""Benchmark: la anualizacion se guia por las observaciones SOLAPADAS (>= 60)."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice, Portfolio
from app.services.portfolio_intelligence_service import (
    MIN_ANNUALIZATION_SESSIONS,
    PortfolioIntelligenceService,
)


def _compare(overlap: int, portfolio_days: int):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "t"
        db.add(Portfolio(name="Main", base_currency="USD", is_default=True))
        spy = Company(ticker="SPY", name="SPY", exchange="NYSE", currency="USD", sector="T",
                      industry="T", company_type="etf", valuation_model="unassigned",
                      special_sources=[], special_risks=[], factor_tags=[])
        db.add(spy)
        db.commit()
        today = date.today()
        px = 100.0
        days = [today - timedelta(days=overlap - i) for i in range(overlap + 1)]
        for i, day in enumerate(days):
            px *= 1.002 if i % 3 else 0.998
            p = Decimal(str(round(px, 4)))
            db.add(MarketPrice(company_id=spy.id, date=day, open=p, high=p, low=p, close=p,
                               adj_close=p, source="probe"))
        db.commit()
        # El portfolio tiene MAS retornos que el solape con el benchmark.
        portfolio = {days[0] - timedelta(days=k): 0.001 for k in range(1, portfolio_days - overlap + 1)}
        portfolio.update({day: (0.003 if i % 3 else -0.002) for i, day in enumerate(days[1:])})
        return PortfolioIntelligenceService()._benchmark_comparison(db, portfolio, today - timedelta(days=400))


def test_short_overlap_does_not_annualize_even_if_portfolio_is_long():
    result = _compare(overlap=48, portfolio_days=70)
    assert result["status"] == "calculated"
    assert result["observations"] == 48
    assert result["benchmark_annualized"] is None
    assert result["portfolio_annualized"] is None
    assert result["alpha_annualized"] is None
    assert result["information_ratio"] is None
    # Lo que no extrapola se conserva.
    assert result["benchmark_twr"] is not None
    assert result["tracking_error"] is not None


def test_enough_overlap_annualizes():
    result = _compare(overlap=MIN_ANNUALIZATION_SESSIONS + 5, portfolio_days=80)
    assert result["observations"] >= MIN_ANNUALIZATION_SESSIONS
    assert result["benchmark_annualized"] is not None
    assert result["portfolio_annualized"] is not None
    assert result["alpha_annualized"] == pytest.approx(
        result["portfolio_annualized"] - result["benchmark_annualized"]
    )
