"""BFIT.AS (Basic-Fit) never resolves to the US ticker BFIT.

The suffix fallback (SAN.MC -> SAN) handed a BFIT.AS request the US BFIT row
whenever BFIT.AS itself was not in the master yet: the ficha, the watchlist
metrics and every /api/companies/BFIT.AS route showed the US homonym.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company
from app.services.company_resolver import resolve_companies, resolve_company


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db, ticker, isin, exchange, currency):
    company = Company(
        ticker=ticker, name=ticker, exchange=exchange, currency=currency, isin=isin,
        company_type="standard", valuation_model="standard_dcf",
    )
    db.add(company)
    db.flush()
    return company


def test_bfit_as_does_not_fall_back_to_us_bfit(db):
    _company(db, "BFIT", "US37954Y4742", "NASDAQ", "USD")
    assert resolve_company(db, "BFIT.AS") is None
    assert resolve_company(db, "bfit.as ") is None
    companies, missing = resolve_companies(db, ["BFIT.AS"])
    assert companies == [] and missing == ["BFIT.AS"]


def test_bfit_as_does_not_fall_back_to_a_base_row_without_isin(db):
    _company(db, "BFIT", None, "NASDAQ", "USD")
    assert resolve_company(db, "BFIT.AS") is None
    assert resolve_companies(db, ["BFIT.AS"])[1] == ["BFIT.AS"]


def test_legacy_basic_fit_base_row_with_its_isin_still_resolves(db):
    legacy = _company(db, "BFIT", "NL0011872650", "EURONEXT AMSTERDAM", "EUR")
    assert resolve_company(db, "BFIT.AS") is legacy
    assert resolve_companies(db, ["BFIT.AS"])[0] == [legacy]


def test_exact_rows_win_and_us_bfit_is_still_bfit(db):
    us = _company(db, "BFIT", "US37954Y4742", "NASDAQ", "USD")
    basic_fit = _company(db, "BFIT.AS", "NL0011872650", "EURONEXT AMSTERDAM", "EUR")
    assert resolve_company(db, "BFIT.AS") is basic_fit
    assert resolve_company(db, "BFIT") is us
    companies, missing = resolve_companies(db, ["BFIT", "BFIT.AS"])
    assert companies == [us, basic_fit] and missing == []


def test_other_suffix_fallbacks_unchanged(db):
    san = _company(db, "SAN", None, "BME", "EUR")
    assert resolve_company(db, "SAN.MC") is san
    assert resolve_companies(db, ["SAN.MC"])[0] == [san]
