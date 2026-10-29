"""Basic-Fit (BFIT.AS, ISIN NL0011872650) and the US ticker BFIT never mix.

After #2887 the Flex import files Basic-Fit trades under BFIT.AS, but cash
rows (dividends, withholding), cancellations and the backfill's
"existing companies only" filter still looked the company up by the bare
broker symbol "BFIT": the dividend was left without a company (and dropped
from the tax report) or credited to the US homonym.
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService

TRADE = (
    '<Trade symbol="BFIT" isin="NL0011872650" listingExchange="AEB" currency="EUR" '
    'buySell="BUY" quantity="10" tradePrice="25" tradeDate="20260310" tradeID="BFIT-1"/>'
)
CASH = (
    '<CashTransaction symbol="BFIT" isin="NL0011872650" currency="EUR" type="Dividends" '
    'amount="8.50" dateTime="20260520" transactionID="BFIT-DIV-1"/>'
    '<CashTransaction symbol="BFIT" isin="NL0011872650" currency="EUR" type="Withholding Tax" '
    'amount="-1.28" dateTime="20260520" transactionID="BFIT-WHT-1"/>'
)
CANCEL = (
    '<Trade symbol="BFIT" isin="NL0011872650" listingExchange="AEB" currency="EUR" '
    'buySell="BUY (Ca.)" quantity="-10" tradePrice="25" tradeDate="20260310" '
    'tradeID="BFIT-1C" origTradeID="BFIT-1"/>'
)
US_TRADE = (
    '<Trade symbol="BFIT" isin="US37954Y4742" listingExchange="NASDAQ" currency="USD" '
    'buySell="BUY" quantity="3" tradePrice="31" tradeDate="20260311" tradeID="US-BFIT-1"/>'
)


def _flex(*rows):
    return "<FlexQueryResponse><FlexStatement>" + "".join(rows) + "</FlexStatement></FlexQueryResponse>"


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr("app.services.company_enrichment_service.CompanyEnrichmentService.enrich", lambda *a: False)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="bfit-homonym", name="Fixture")
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


def _by_external(db, external_id):
    return db.query(Transaction).filter_by(external_id=external_id).one()


@pytest.mark.parametrize("with_us_homonym", [False, True])
def test_basic_fit_dividend_and_withholding_go_to_bfit_as(db, with_us_homonym):
    us = _us_bfit(db) if with_us_homonym else None
    IBKRImportService().import_flex_xml(db, _flex(TRADE, CASH))
    basic_fit = db.query(Company).filter_by(ticker="BFIT.AS").one()
    dividend = _by_external(db, "BFIT-DIV-1")
    withholding = _by_external(db, "BFIT-WHT-1")
    assert dividend.company_id == basic_fit.id
    assert withholding.company_id == basic_fit.id
    assert (dividend.action, dividend.price) == ("dividend", Decimal("8.50"))
    assert withholding.action == "withholding"
    if us is not None:
        assert db.query(Transaction).filter_by(company_id=us.id).count() == 0


@pytest.mark.parametrize("with_us_homonym", [False, True])
def test_basic_fit_cancellation_finds_its_original(db, with_us_homonym):
    if with_us_homonym:
        _us_bfit(db)
    IBKRImportService().import_flex_xml(db, _flex(TRADE))
    result = IBKRImportService().import_flex_xml(db, _flex(CANCEL))
    assert not [e for e in result.get("row_errors", []) if "Anulacion" in e]
    assert _by_external(db, "BFIT-1").action == "cancelled"
    basic_fit = db.query(Company).filter_by(ticker="BFIT.AS").one()
    assert _by_external(db, "BFIT-1C").company_id == basic_fit.id


def test_backfill_existing_only_matches_bfit_as_not_the_us_symbol(db):
    basic_fit = Company(
        ticker="BFIT.AS", name="Basic-Fit N.V.", exchange="EURONEXT AMSTERDAM", currency="EUR",
        isin="NL0011872650", company_type="standard", valuation_model="standard_dcf",
    )
    db.add(basic_fit)
    db.flush()
    IBKRImportService().import_flex_xml(
        db, _flex(TRADE), trades_only=True, only_existing_companies=True, dry_run=False,
    )
    assert _by_external(db, "BFIT-1").company_id == basic_fit.id


def test_backfill_existing_only_does_not_create_bfit_as_because_us_bfit_exists(db):
    _us_bfit(db)
    IBKRImportService().import_flex_xml(
        db, _flex(TRADE), trades_only=True, only_existing_companies=True,
    )
    assert db.query(Company).filter_by(ticker="BFIT.AS").count() == 0
    assert db.query(Transaction).count() == 0


def test_us_bfit_rows_still_resolve_to_the_us_company(db):
    us = _us_bfit(db)
    IBKRImportService().import_flex_xml(
        db,
        _flex(
            US_TRADE,
            '<CashTransaction symbol="BFIT" isin="US37954Y4742" currency="USD" type="Dividends" '
            'amount="0.40" dateTime="20260601" transactionID="US-BFIT-DIV"/>',
        ),
    )
    assert _by_external(db, "US-BFIT-1").company_id == us.id
    assert _by_external(db, "US-BFIT-DIV").company_id == us.id
    assert db.query(Company).filter_by(ticker="BFIT.AS").count() == 0
