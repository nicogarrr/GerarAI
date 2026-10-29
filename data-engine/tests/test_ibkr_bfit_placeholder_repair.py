"""#2861: a BFIT.AS stub created before the first import must not break it.

The ficha, the search box and thesis generation create BFIT.AS with exchange
UNKNOWN and currency USD; Finnhub enrichment later labels the exchange
"NYSE EURONEXT - EURONEXT AMSTERDAM". The Flex import must correct such a
placeholder to the ISIN-verified listing instead of rejecting the whole file,
and keep failing for a genuinely conflicting row.
"""
from xml.etree.ElementTree import fromstring

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Position, Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportError, IBKRImportService
from app.services.listing_identity import BASIC_FIT

FLEX = (
    '<FlexQueryResponse><FlexStatement>'
    '<OpenPosition symbol="BFIT" isin="NL0011872650" listingExchange="AEB" currency="EUR" position="2" '
    'markPrice="30" positionValue="60" costBasisPrice="25" reportDate="20261028"/>'
    '<Trade symbol="BFIT" isin="NL0011872650" listingExchange="XAMS" currency="EUR" buySell="BUY" '
    'quantity="2" tradePrice="25" tradeDate="20261020" tradeID="BFIT-1"/>'
    '</FlexStatement></FlexQueryResponse>'
)
ELEMENT = '<Trade symbol="BFIT" isin="NL0011872650" listingExchange="AEB" currency="EUR"/>'


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr("app.services.company_enrichment_service.CompanyEnrichmentService.enrich", lambda *a: False)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="bfit-stub", name="Fixture")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        yield session


def _stub(db, exchange, currency, isin=None):
    company = Company(
        ticker="BFIT.AS", name="BFIT.AS", exchange=exchange, currency=currency, isin=isin,
        company_type="standard", valuation_model="standard_dcf",
    )
    db.add(company)
    db.flush()
    return company


PLACEHOLDERS = [
    ("NYSE EURONEXT - EURONEXT AMSTERDAM", "EUR"),
    ("UNKNOWN", "EUR"),
    ("UNKNOWN", "USD"),
]


@pytest.mark.parametrize("exchange,currency", PLACEHOLDERS)
def test_flex_import_corrects_placeholder_basic_fit_row(db, exchange, currency):
    stub = _stub(db, exchange, currency)
    IBKRImportService().import_flex_xml(db, FLEX)
    company = db.query(Company).filter_by(ticker="BFIT.AS").one()
    assert company.id == stub.id
    assert (company.isin, company.exchange, company.currency) == (
        BASIC_FIT.isin, "EURONEXT AMSTERDAM", "EUR")
    assert db.query(Position).one().company_id == company.id
    assert db.query(Transaction).one().company_id == company.id


@pytest.mark.parametrize("exchange", ["", "NYSE EURONEXT - AMSTERDAM", "Euronext Amsterdam"])
def test_other_placeholder_and_amsterdam_names_are_accepted(db, exchange):
    _stub(db, exchange, "EUR")
    company = IBKRImportService()._company(db, {}, "BFIT", fromstring(ELEMENT))
    assert (company.isin, company.exchange, company.currency) == (BASIC_FIT.isin, "EURONEXT AMSTERDAM", "EUR")


def test_verified_row_with_finnhub_label_is_accepted(db):
    _stub(db, "NYSE EURONEXT - EURONEXT AMSTERDAM", "EUR", isin=BASIC_FIT.isin)
    company = IBKRImportService()._company(db, {}, "BFIT", fromstring(ELEMENT))
    assert (company.exchange, company.currency) == ("EURONEXT AMSTERDAM", "EUR")


@pytest.mark.parametrize("exchange,currency,isin", [
    ("NASDAQ", "USD", None),                     # another venue
    ("XETRA", "EUR", None),                      # another venue
    ("UNKNOWN", "GBP", None),                    # another currency
    ("EURONEXT AMSTERDAM", "USD", BASIC_FIT.isin),  # verified row, wrong currency
    ("XETRA", "EUR", BASIC_FIT.isin),            # verified row, other venue
])
def test_conflicting_existing_row_still_fails(db, exchange, currency, isin):
    _stub(db, exchange, currency, isin)
    with pytest.raises(IBKRImportError, match="listado existente"):
        IBKRImportService()._company(db, {}, "BFIT", fromstring(ELEMENT))


def test_row_with_another_isin_still_fails(db):
    _stub(db, "UNKNOWN", "USD", isin="US0000000001")
    with pytest.raises(IBKRImportError, match="otro ISIN"):
        IBKRImportService()._company(db, {}, "BFIT", fromstring(ELEMENT))
    with pytest.raises(IBKRImportError):
        IBKRImportService().import_flex_xml(db, FLEX)
