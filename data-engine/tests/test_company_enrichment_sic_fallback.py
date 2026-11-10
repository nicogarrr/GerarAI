"""Real SQLite SIC fallback through enrichment, without provider access."""

from types import SimpleNamespace
from unittest.mock import Mock

import httpx
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
    engine.dispose()


def company(ticker="FIXTURE", sector="Unknown", industry="Unknown", cik="123"):
    return Company(
        ticker=ticker,
        name="Curated company",
        exchange="NYSE",
        currency="USD",
        sector=sector,
        industry=industry,
        cik=cik,
        factor_tags=[],
        company_type="quality",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
    )


def service(lookup):
    # HTTP client is a real in-process transport that fails if called.
    client = httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("unexpected HTTP")))
    return CompanyEnrichmentService(
        settings=SimpleNamespace(finnhub_api_key=None), client=client, sic_lookup=lookup
    )


def test_enrich_without_finnhub_profile_uses_sic_calibration_and_preserves_identity(db):
    curated = company("CURATED", "Materials", "Custom (SIC 7370)")
    target = company()
    db.add_all([curated, target])
    db.commit()
    lookup = Mock(return_value=(7370, "COMPUTER SERVICES"))
    enrichment = service(lookup)
    try:
        assert enrichment.enrich(db, target, persist=False)
        lookup.assert_called_once_with("123")
        assert target.industry == "Computer services (SIC 7370)"
        assert target.sector == "Materials"  # calibration, not the default IT range
        assert (target.name, target.exchange, target.currency) == ("Curated company", "NYSE", "USD")
        assert target.enrichment_attempted_at is not None
        assert not enrichment._sic_fallback(db, target)
        lookup.assert_called_once()
    finally:
        enrichment.close()


def test_existing_industry_beats_sic_range_for_unknown_sector(db):
    target = company(industry="Health Care")
    db.add(target)
    db.commit()
    lookup = Mock(return_value=(6282, "Investment advice"))
    enrichment = service(lookup)
    try:
        assert enrichment._sic_fallback(db, target)
        assert target.sector == "Health Care" and target.industry == "Health Care"
    finally:
        enrichment.close()


def test_sic_lookup_failure_is_nonfatal_and_keeps_unknown_fields(db):
    target = company()
    db.add(target)
    db.commit()
    lookup = Mock(side_effect=RuntimeError("local SEC failure"))
    enrichment = service(lookup)
    try:
        assert not enrichment.enrich(db, target)
        assert target.sector == target.industry == "Unknown"
        assert target.enrichment_attempted_at is not None
        lookup.assert_called_once_with("123")
    finally:
        enrichment.close()


@pytest.mark.parametrize("cik", [None, ""])
def test_missing_cik_never_looks_up_sic(db, cik):
    lookup = Mock(side_effect=AssertionError("must not look up missing CIK"))
    enrichment = service(lookup)
    try:
        assert not enrichment._sic_fallback(db, company(cik=cik))
        lookup.assert_not_called()
    finally:
        enrichment.close()
