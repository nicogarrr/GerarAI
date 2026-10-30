"""Desviacion del plan: casos limite.

- Un objetivo por ticker guardado en minusculas («nvda») debe leer el peso de
  la posicion NVDA; antes leia 0 % y sugeria comprar lo que ya se tiene.
- Con la cartera vacia (valor 0) no hay nada que reequilibrar: antes salia una
  sugerencia «Comprar 0,00 €» por cada objetivo.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position
from app.services.investment_plan_service import InvestmentPlanService
from tests.test_investment_plan_service import _plan


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(ticker, sector="Tech"):
    return Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector=sector, industry=sector, company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )


def _position(db, ticker, value):
    company = _company(ticker)
    db.add(company)
    db.flush()
    db.add(Position(company_id=company.id, quantity=Decimal("10"), market_price=Decimal("1"),
                    currency="EUR", market_value_base=Decimal(value), as_of=date(2026, 9, 20)))


def test_ticker_target_matches_position_regardless_of_case(db):
    service = InvestmentPlanService()
    _plan(service, db, target_allocations=[
        {"kind": "ticker", "label": "nvda", "target_pct": 50, "band_pct": 5},
        {"kind": "ticker", "label": "AAPL", "target_pct": 50, "band_pct": 5},
    ])
    _position(db, "NVDA", "500")
    _position(db, "AAPL", "500")
    db.commit()

    drift = service.drift_analysis(db)
    by_label = {d["label"]: d for d in drift["deviations"]}
    assert by_label["nvda"]["current_pct"] == 50.0
    assert by_label["nvda"]["within_band"] is True
    assert drift["suggestions"] == []


def test_empty_portfolio_has_no_zero_amount_suggestions(db):
    service = InvestmentPlanService()
    _plan(service, db, target_allocations=[
        {"kind": "ticker", "label": "MSFT", "target_pct": 60, "band_pct": 5},
        {"kind": "sector", "label": "Tech", "target_pct": 100, "band_pct": 5},
    ])
    db.commit()

    drift = service.drift_analysis(db)
    assert drift["portfolio_value_base"] == 0.0
    assert drift["status"] == "empty_portfolio"
    assert drift["suggestions"] == []
    assert all(s["amount_base"] > 0 for s in drift["suggestions"])
