"""Broker symbol collisions must not turn Basic-Fit into a US ETF."""
from xml.etree.ElementTree import fromstring

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company
from app.services.ibkr_import_service import IBKRImportError, IBKRImportService
from app.services.listing_identity import BASIC_FIT, reviewed_listing
from app.services.propicks_price_service import yahoo_symbol


def test_reviewed_basic_fit_isin_and_provider_symbols():
    listing = reviewed_listing("nl0011872650")
    assert listing == BASIC_FIT
    assert listing.yahoo == "BFIT.AS"
    assert listing.stooq == "bfit.nl"
    assert reviewed_listing("US0000000000") is None


def test_import_uses_isin_before_us_homonym_and_preserves_existing_holding(monkeypatch):
    monkeypatch.setattr("app.services.company_enrichment_service.CompanyEnrichmentService.enrich", lambda *a: False)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        old = Company(ticker="BFIT", name="Global X ETF", exchange="NASDAQ", currency="USD", company_type="standard", valuation_model="standard_dcf")
        db.add(old)
        db.flush()
        service = IBKRImportService()
        element = fromstring('<OpenPosition symbol="BFIT" isin="NL0011872650" listingExchange="AEB" currency="EUR"/>')
        company = service._company(db, {}, "BFIT", element)
        assert company.id != old.id
        assert (old.ticker, old.name, old.currency) == ("BFIT", "Global X ETF", "USD")
        assert (company.ticker, company.name, company.currency, company.isin) == (
            "BFIT.AS", "Basic-Fit N.V.", "EUR", "NL0011872650")
        assert yahoo_symbol(company) == "BFIT.AS"
        assert service._company(db, {}, "BFIT", element).id == company.id
        with pytest.raises(IBKRImportError, match="divisa Flex"):
            service._company(db, {}, "BFIT", fromstring('<Trade isin="NL0011872650" currency="USD" listingExchange="AEB"/>'))


def test_unknown_listing_uses_flex_currency_not_usd_default(monkeypatch):
    monkeypatch.setattr("app.services.company_enrichment_service.CompanyEnrichmentService.enrich", lambda *a: False)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        service = IBKRImportService()
        company = service._company(db, {}, "EURO", fromstring('<Trade currency="EUR" listingExchange="AEB"/>'))
        assert company.currency == "EUR"
        assert company.exchange == "AEB"
        unknown = service._company(db, {}, "NOCUR", fromstring('<Trade/>'))
        assert unknown.currency == ""
        assert yahoo_symbol(unknown) is None


def test_isin_price_resolution_rejects_wrong_currency():
    company = Company(ticker="BFIT", isin=BASIC_FIT.isin, currency="EUR")
    assert yahoo_symbol(company) == "BFIT.AS"
    company.currency = "USD"
    assert yahoo_symbol(company) is None


def test_full_flex_import_resolves_basic_fit(monkeypatch):
    from app.models import Position, Tenant, Transaction
    monkeypatch.setattr("app.services.company_enrichment_service.CompanyEnrichmentService.enrich", lambda *a: False)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id="listing-fixture", name="Fixture")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id
        xml = '<FlexQueryResponse><FlexStatement><OpenPosition symbol="BFIT" isin="NL0011872650" listingExchange="AEB" currency="EUR" position="2" markPrice="30" positionValue="60" costBasisPrice="25" reportDate="20261028"/><Trade symbol="BFIT" isin="NL0011872650" listingExchange="XAMS" currency="EUR" buySell="BUY" quantity="2" tradePrice="25" tradeDate="20261020" tradeID="BFIT-1"/></FlexStatement></FlexQueryResponse>'
        IBKRImportService().import_flex_xml(db, xml)
        company = db.query(Company).filter_by(ticker="BFIT.AS").one()
        assert db.query(Position).one().company_id == company.id
        assert db.query(Transaction).one().company_id == company.id
        assert db.query(Position).one().currency == "EUR"


@pytest.mark.parametrize("exchange", ["XETRA", "SMART", "", "UNKNOWN"])
def test_reviewed_isin_rejects_different_or_ambiguous_venue(exchange):
    element = fromstring(f'<Trade isin="NL0011872650" currency="EUR" listingExchange="{exchange}"/>')
    with pytest.raises(IBKRImportError, match="plaza Flex"):
        IBKRImportService()._company(None, {}, "BFIT", element)


@pytest.mark.parametrize("currency,exchange", [("USD", "NASDAQ"), ("EUR", "XETRA"), ("USD", "EURONEXT AMSTERDAM")])
def test_reviewed_listing_cache_cannot_bypass_identity_validation(currency, exchange):
    cached = Company(ticker="BFIT.AS", isin=BASIC_FIT.isin, currency=currency, exchange=exchange)
    element = fromstring('<Trade isin="NL0011872650" currency="EUR" listingExchange="AEB"/>')
    with pytest.raises(IBKRImportError, match="caché"):
        IBKRImportService()._company(None, {"BFIT.AS": cached}, "BFIT", element)
