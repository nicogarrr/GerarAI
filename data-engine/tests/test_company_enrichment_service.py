"""CompanyEnrichmentService contract tests.

The catalogue seed is NOT the source of truth for display names:
placeholder names/exchanges get enriched from the market-data API, good
records are never touched, and unusable API payloads change nothing.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services.company_enrichment_service import CompanyEnrichmentService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class _Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data


class _Client:
    def __init__(self, data):
        self._data = data
        self.calls = []

    def get(self, url, params=None):
        self.calls.append(url)
        return _Resp(self._data)


class _Settings:
    finnhub_api_key = "test-key"


def _company(
    db: Session,
    *,
    name: str,
    exchange: str = "NASDAQ",
    ticker: str = "XYZ",
    sector: str = "Tech",
    industry: str = "Tech",
) -> Company:
    company = Company(
        ticker=ticker, name=name, exchange=exchange, currency="USD",
        sector=sector, industry=industry, company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_needs_enrichment_detects_placeholders(db):
    assert CompanyEnrichmentService.needs_enrichment(_company(db, name="T1", ticker="T1")) is True  # name equals its ticker
    assert CompanyEnrichmentService.needs_enrichment(_company(db, name="ACME_CORP", ticker="T2")) is True
    assert CompanyEnrichmentService.needs_enrichment(_company(db, name="", ticker="T3")) is True
    assert CompanyEnrichmentService.needs_enrichment(
        _company(db, name="Real Name", exchange="UNKNOWN", ticker="T4")
    ) is True
    assert CompanyEnrichmentService.needs_enrichment(
        _company(db, name="Real Name", ticker="T5")
    ) is False


def test_needs_enrichment_detects_placeholder_sector(db):
    # Buen nombre/exchange pero sector sin clasificar: antes era "already_ok"
    # y nunca se clasificaba (CF Industries / INVA en ProPicks).
    assert CompanyEnrichmentService.needs_enrichment(
        _company(db, name="CF Industries Holdings, Inc.", ticker="CF", sector="Unknown", industry="Unknown")
    ) is True
    assert CompanyEnrichmentService.needs_enrichment(
        _company(db, name="CF Industries Holdings, Inc.", ticker="CF2", sector="Materials", industry="Chemicals")
    ) is False


def test_enrich_applies_profile_and_marks_changed(db):
    company = _company(db, name="XYZ", exchange="UNKNOWN")
    client = _Client({
        "name": "Xylem Robotics Inc",
        "exchange": "NASDAQ NMS - GLOBAL MARKET",
        "finnhubIndustry": "Technology",
        "currency": "USD",
    })
    service = CompanyEnrichmentService(settings=_Settings(), client=client)
    assert service.enrich(db, company) is True
    assert company.name == "Xylem Robotics Inc"
    assert company.exchange == "NASDAQ NMS - GLOBAL MARKET"
    assert company.industry == "Technology"
    assert "profile2" in client.calls[0]


def test_enrich_never_touches_good_record_and_skips_api(db):
    company = _company(db, name="Apple Inc")
    client = _Client({"name": "Wrong Name"})
    service = CompanyEnrichmentService(settings=_Settings(), client=client)
    assert service.enrich(db, company) is False
    assert company.name == "Apple Inc"
    assert client.calls == []  # no API call for a healthy record


def test_enrich_without_api_name_changes_nothing(db):
    company = _company(db, name="XYZ")
    client = _Client({"finnhubIndustry": "Technology"})  # no usable name
    service = CompanyEnrichmentService(settings=_Settings(), client=client)
    assert service.enrich(db, company) is False
    assert company.name == "XYZ"


def test_enrich_classifies_placeholder_sector_from_industry(db):
    company = _company(db, name="CF Industries Holdings, Inc.", sector="Unknown", industry="Unknown")
    client = _Client({
        "name": "CF Industries Holdings, Inc.",
        "exchange": "NYSE",
        "finnhubIndustry": "Chemicals",
        "currency": "USD",
    })
    service = CompanyEnrichmentService(settings=_Settings(), client=client)
    assert service.enrich(db, company) is True
    assert company.industry == "Chemicals"
    assert company.sector == "Materials"  # mapeo GICS declarado, no inventado


def test_enrich_leaves_unknown_sector_when_industry_unmapped(db):
    company = _company(db, name="Innventure, Inc.", sector="Unknown", industry="Unknown")
    client = _Client({
        "name": "Innventure, Inc.",
        "exchange": "NASDAQ",
        "finnhubIndustry": "Holding Companies",  # no mapeada: honesto, no se inventa
        "currency": "USD",
    })
    service = CompanyEnrichmentService(settings=_Settings(), client=client)
    service.enrich(db, company)
    assert company.industry == "Holding Companies"
    assert company.sector == "Unknown"


def test_enrich_ignores_na_industry(db):
    company = _company(db, name="XYZ")
    client = _Client({"name": "Xylem Robotics", "finnhubIndustry": "N/A"})
    service = CompanyEnrichmentService(settings=_Settings(), client=client)
    assert service.enrich(db, company) is True
    assert company.name == "Xylem Robotics"
    assert company.industry == "Tech"  # N/A never overwrites


def test_enrich_sets_sector_from_declared_mapping(db):
    company = _company(db, name="XYZ", ticker="XYZ", exchange="UNKNOWN")
    company.sector = "Unknown"
    db.commit()
    profile = {
        "name": "Xylem Semiconductors",
        "exchange": "NASDAQ",
        "finnhubIndustry": "Semiconductors",
        "currency": "USD",
    }
    service = CompanyEnrichmentService(settings=_Settings(), client=_Client(profile))
    assert service.enrich(db, company) is True
    assert company.industry == "Semiconductors"
    assert company.sector == "Information Technology"


def test_enrich_maps_finnhub_communications_to_information_technology(db):
    """F155: la industria Finnhub "Communications" es GICS Communications
    Equipment (CSCO, ANET...), sector Information Technology, no
    Communication Services."""
    company = _company(db, name="CSCO", ticker="CSCO", exchange="UNKNOWN")
    company.sector = "Unknown"
    db.commit()
    profile = {
        "name": "Cisco Systems Inc",
        "exchange": "NASDAQ",
        "finnhubIndustry": "Communications",
        "currency": "USD",
    }
    service = CompanyEnrichmentService(settings=_Settings(), client=_Client(profile))
    assert service.enrich(db, company) is True
    assert company.industry == "Communications"
    assert company.sector == "Information Technology"


def test_enrich_keeps_real_sector_and_unknown_industry_stays_honest(db):
    company = _company(db, name="XYZ", ticker="XYZ", exchange="UNKNOWN")
    company.sector = "Unknown"
    db.commit()
    profile = {
        "name": "Mystery Corp",
        "exchange": "NYSE",
        "finnhubIndustry": "Underwater Basket Weaving",
        "currency": "USD",
    }
    service = CompanyEnrichmentService(settings=_Settings(), client=_Client(profile))
    assert service.enrich(db, company) is True
    assert company.industry == "Underwater Basket Weaving"
    assert company.sector == "Unknown"  # nunca se inventa un sector


def test_enrich_does_not_overwrite_existing_sector(db):
    company = _company(db, name="XYZ", ticker="XYZ", exchange="UNKNOWN")
    company.sector = "Energy"
    db.commit()
    profile = {
        "name": "Renamed Corp",
        "exchange": "NYSE",
        "finnhubIndustry": "Semiconductors",
        "currency": "USD",
    }
    service = CompanyEnrichmentService(settings=_Settings(), client=_Client(profile))
    service.enrich(db, company)
    assert company.sector == "Energy"


def test_enrich_curated_record_keeps_name_exchange_currency(db):
    """Auditor 2026-10-19 (#1871): ficha curada con SOLO el sector en Unknown.
    Finnhub devuelve nombre/bolsa/divisa del proveedor (GBX para LSE) y antes
    los pisaba todos: los campos curados no se tocan, solo se clasifica."""
    company = _company(
        db,
        name="Georgia Capital PLC",
        exchange="LSE",
        ticker="CGEO",
        sector="Unknown",
        industry="Unknown",
    )
    company.currency = "GBP"
    db.commit()
    client = _Client({
        "name": "GEORGIA CAPITAL PLC",
        "exchange": "London Stock Exchange",
        "finnhubIndustry": "Financial Services",
        "currency": "GBX",
    })
    service = CompanyEnrichmentService(settings=_Settings(), client=client)
    assert service.enrich(db, company) is True
    assert company.name == "Georgia Capital PLC"
    assert company.exchange == "LSE"
    assert company.currency == "GBP"
    assert company.industry == "Financial Services"
    assert company.sector == "Financials"
