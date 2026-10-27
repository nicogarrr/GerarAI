"""PER con EPS en acciones actuales: si hubo split tras el cierre del
ejercicio del EPS, precio_hoy / eps_reportado infla el PER por el factor
del split. El EPS se divide por el factor acumulado posterior a SU
periodo (espejo del ajuste de recuentos, que multiplica)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    Company,
    CorporateAction,
    FinancialFact,
    MarketPrice,
    Tenant,
)
from app.services.screener_fundamentals import load_screener_ratios
from app.services.split_adjustment import (
    cumulative_split_factor_after,
    period_end_date,
)

TODAY = date(2026, 9, 25)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Tenant.__table__, Company.__table__, FinancialFact.__table__,
            MarketPrice.__table__, CorporateAction.__table__,
        ],
    )
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str = "AAPL") -> Company:
    row = Company(
        ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ", currency="USD",
        sector="Technology", industry="Hardware", company_type="operating",
        valuation_model="standard_dcf",
    )
    db.add(row)
    db.flush()
    return row


def _fact(db, company, metric, value, unit, *, year=2024, period=None):
    row = FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(value), unit=unit,
        period=period or f"{year}-12-31:FY", fiscal_year=year,
        fiscal_quarter="FY", source_type="SEC", is_reported=True,
    )
    db.add(row)
    db.flush()
    return row


def _price(db, company, close):
    db.add(MarketPrice(company_id=company.id, date=TODAY,
                       close=Decimal(close), adj_close=Decimal(close),
                       source="yahoo"))
    db.flush()


def _split(db, company, effective: date, ratio: str):
    db.add(CorporateAction(
        company_id=company.id, action_type="split", ratio=Decimal(ratio),
        effective_date=effective, description="test split",
    ))
    db.flush()


def test_pe_divides_eps_by_post_period_split_factor(db):
    """EPS FY2024 = 6 (base pre-split), split 4:1 en 2025, cierre hoy 60:
    PER = 60 / (6/4) = 40, no 10."""
    company = _company(db)
    _price(db, company, "60")
    _fact(db, company, "eps_diluted", "6", "USD/share")
    _split(db, company, date(2025, 6, 9), "4")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pe"] == pytest.approx(40.0)
    prov = result["ratioProvenance"]["facts"]["pe"]
    assert prov["split_factor"] == "4"
    assert "cumulative_split_factor" in prov["calculation"]


def test_pe_ignores_splits_before_period_end(db):
    """Split ANTES del cierre del ejercicio del EPS: ya esta dentro del EPS
    reportado, no se ajusta."""
    company = _company(db)
    _price(db, company, "60")
    _fact(db, company, "eps_diluted", "6", "USD/share")
    _split(db, company, date(2024, 6, 9), "4")  # antes de 2024-12-31
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pe"] == pytest.approx(10.0)
    assert "split_factor" not in result["ratioProvenance"]["facts"]["pe"]


def test_pe_stacks_multiple_splits(db):
    company = _company(db)
    _price(db, company, "60")
    _fact(db, company, "eps_diluted", "6", "USD/share")
    _split(db, company, date(2025, 1, 15), "2")
    _split(db, company, date(2025, 7, 15), "2")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pe"] == pytest.approx(40.0)  # 60 / (6/4)


def test_helpers_never_guess():
    assert cumulative_split_factor_after([(date(2025, 1, 1), Decimal(4))], None) == 1
    assert period_end_date("garbage") is None
    assert period_end_date("2025-09-27:FY") == date(2025, 9, 27)


def test_pb_multiplies_shares_by_post_period_split_factor(db):
    """P/B con acciones en base actual: patrimonio FY2024 = 1200, acciones
    diluidas FY2024 = 100 (pre-split), split 4:1 en 2025, cierre hoy 30.
    BVPS actual = 1200 / (100 * 4) = 3 -> P/B = 30 / 3 = 10, no 2,5
    (30 / (1200/100)), que infravaloraba el multiplo por el factor del split."""
    company = _company(db)
    _price(db, company, "30")
    _fact(db, company, "total_equity", "1200", "USD")
    _fact(db, company, "shares_diluted", "100", "shares")
    _split(db, company, date(2025, 6, 9), "4")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pb"] == pytest.approx(10.0)
    prov = result["ratioProvenance"]["facts"]["pb"]
    assert prov["split_factor"] == "4"


def test_pb_ignores_splits_before_period_end(db):
    """Split ANTES del cierre: el recuento reportado ya lo incluye."""
    company = _company(db)
    _price(db, company, "30")
    _fact(db, company, "total_equity", "1200", "USD")
    _fact(db, company, "shares_diluted", "400", "shares")
    _split(db, company, date(2024, 6, 9), "4")
    result = load_screener_ratios(db, {"AAPL"}, today=TODAY)["AAPL"]
    assert result["pb"] == pytest.approx(10.0)
    assert "split_factor" not in result["ratioProvenance"]["facts"]["pb"]
