"""IBKR CSV with an ISIN column: Basic-Fit «BFIT» goes to BFIT.AS.

Without reading the ISIN, a CSV row «BFIT, NL0011872650, EUR» was filed under
the bare ticker BFIT (the US homonym when it exists) while the Flex import
files the same holding under BFIT.AS: two companies for one position.
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService

HEADER = "Symbol,ISIN,Buy/Sell,Quantity,TradePrice,TradeDate,Currency,IBCommission\n"
BFIT_ROW = "BFIT,NL0011872650,BUY,10,25.5,2026-03-10,EUR,-1.2\n"
US_ROW = "BFIT,US37954Y4742,BUY,3,31,2026-03-11,USD,-1\n"


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr("app.services.company_enrichment_service.CompanyEnrichmentService.enrich", lambda *a: False)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="bfit-csv", name="Fixture")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        yield session


def _us_bfit(db):
    company = Company(
        ticker="BFIT", name="Global X Health & Wellness ETF", exchange="NASDAQ", currency="USD",
        isin="US37954Y4742", company_type="standard", valuation_model="standard_dcf",
    )
    db.add(company)
    db.flush()
    return company


@pytest.mark.parametrize("with_us_homonym", [False, True])
def test_csv_isin_routes_basic_fit_to_bfit_as(db, with_us_homonym):
    us = _us_bfit(db) if with_us_homonym else None
    result = IBKRImportService().import_ibkr_csv(db, HEADER + BFIT_ROW)
    assert result["trades_imported"] == 1, result
    basic_fit = db.query(Company).filter_by(ticker="BFIT.AS").one()
    assert (basic_fit.isin, basic_fit.exchange, basic_fit.currency) == (
        "NL0011872650", "EURONEXT AMSTERDAM", "EUR")
    trade = db.query(Transaction).one()
    assert trade.company_id == basic_fit.id
    assert (trade.quantity, trade.price, trade.currency) == (Decimal("10"), Decimal("25.5"), "EUR")
    if us is not None:
        assert db.query(Transaction).filter_by(company_id=us.id).count() == 0


def test_csv_reimport_does_not_duplicate_basic_fit(db):
    IBKRImportService().import_ibkr_csv(db, HEADER + BFIT_ROW)
    again = IBKRImportService().import_ibkr_csv(db, HEADER + BFIT_ROW)
    assert again["trades_imported"] == 0 and again["duplicate_trades"] == 1
    assert db.query(Transaction).count() == 1


def test_csv_us_isin_stays_on_the_us_ticker(db):
    us = _us_bfit(db)
    IBKRImportService().import_ibkr_csv(db, HEADER + US_ROW)
    assert db.query(Transaction).one().company_id == us.id
    assert db.query(Company).filter_by(ticker="BFIT.AS").count() == 0


def test_csv_basic_fit_isin_with_wrong_currency_is_a_row_error(db):
    result = IBKRImportService().import_ibkr_csv(
        db, HEADER + "BFIT,NL0011872650,BUY,10,25.5,2026-03-10,USD,-1.2\n"
    )
    assert result["trades_imported"] == 0 and result["rows_skipped"] == 1
    assert "BFIT" in result["row_errors"][0]
    assert db.query(Transaction).count() == 0


def test_csv_without_isin_column_is_unchanged(db):
    IBKRImportService().import_ibkr_csv(
        db,
        "Symbol,Buy/Sell,Quantity,TradePrice,TradeDate,Currency\nBFIT,BUY,3,31,2026-03-11,USD\n",
    )
    trade = db.query(Transaction).one()
    assert db.get(Company, trade.company_id).ticker == "BFIT"


NO_ISIN_HEADER = "Symbol,Buy/Sell,Quantity,TradePrice,TradeDate,Currency,IBCommission\n"


@pytest.mark.parametrize("header,row", [
    (NO_ISIN_HEADER, "BFIT,BUY,10,25.5,2026-03-10,EUR,-1.2\n"),
    (HEADER, "BFIT,,BUY,10,25.5,2026-03-10,EUR,-1.2\n"),
])
def test_bfit_in_eur_without_isin_goes_to_review_not_to_us_bfit(db, header, row):
    us = _us_bfit(db)
    result = IBKRImportService().import_ibkr_csv(db, header + row)
    assert result["trades_imported"] == 0, result
    assert db.query(Transaction).filter_by(company_id=us.id).count() == 0
    assert db.query(Company).filter_by(ticker="BFIT.AS").count() == 0
    assert any("pendiente de revisión" in error and "BFIT.AS" in error for error in result["row_errors"])


def test_bfit_in_usd_without_isin_still_imports_as_us_bfit(db):
    us = _us_bfit(db)
    result = IBKRImportService().import_ibkr_csv(db, NO_ISIN_HEADER + "BFIT,BUY,3,31,2026-03-11,USD,-1\n")
    assert result["trades_imported"] == 1, result
    assert db.query(Transaction).filter_by(company_id=us.id).count() == 1
