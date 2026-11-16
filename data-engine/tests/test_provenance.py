"""P1a: provenance envelope — unit + contract tests."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.provenance import Coverage, SourceKind, coverage_for_age, provenance


def test_provenance_block_shape():
    fetched = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    block = provenance("SEC EDGAR", SourceKind.OFFICIAL, source_url="https://www.sec.gov/",
                       fetched_at=fetched, coverage=Coverage.OK)
    assert block["source"] == "SEC EDGAR"
    assert block["source_kind"] == "official"
    assert block["source_url"] == "https://www.sec.gov/"
    assert block["coverage"] == "ok"
    assert block["fetched_at"] == fetched.isoformat()  # the real fetch time, verbatim
    assert "note" not in block


def test_omitted_fetched_at_is_null_never_fabricated():
    """A caller without a real fetch time must surface fetched_at=None.

    Regression: provenance() used to substitute datetime.now(UTC) on omission,
    making cached/stale/unavailable data look freshly fetched (Lote 1, hallazgo 1).
    """
    before = datetime.now(UTC)
    block = provenance("SEC EDGAR", SourceKind.OFFICIAL, coverage=Coverage.UNAVAILABLE)
    after = datetime.now(UTC)
    assert block["fetched_at"] is None
    # and it is not a hidden now() either (paranoia: the value is null, period)
    assert block["fetched_at"] != before.isoformat()
    assert block["fetched_at"] != after.isoformat()


def test_source_kind_tiers_are_distinct():
    assert {k.value for k in SourceKind} == {"official", "issuer", "exchange", "unofficial", "internal"}
    block = provenance("Yahoo Finance", SourceKind.UNOFFICIAL, note="fuente no oficial")
    assert block["source_kind"] == "unofficial"
    assert block["note"] == "fuente no oficial"


def test_invalid_kind_rejected():
    with pytest.raises(ValueError):
        provenance("X", "authoritative")  # not a tier — must fail loudly


def test_coverage_for_age():
    now = datetime.now(UTC)
    assert coverage_for_age("sec_form4", now - timedelta(minutes=5)) == Coverage.OK
    assert coverage_for_age("sec_form4", now - timedelta(hours=2)) == Coverage.STALE
    assert coverage_for_age("fred", now - timedelta(days=3)) == Coverage.OK
    assert coverage_for_age("unknown_family", now - timedelta(hours=7)) == Coverage.STALE
    assert coverage_for_age("sec_form4", now, partial=True) == Coverage.PARTIAL
    assert coverage_for_age("sec_form4", now, empty=True) == Coverage.UNAVAILABLE


# ---- Contract tests: endpoints surface the standard provenance block ----


def test_insider_signals_carry_provenance_block(monkeypatch):
    """Contract: /api/insider/signals result includes official SEC provenance."""
    from app.services import insider_service
    from app.services.connectors import form4 as form4_connector

    monkeypatch.setattr(insider_service, "_cik_for_ticker", lambda ticker, client=None: "0001234567")
    filing = {
        "form": "4",
        "accession_number": "0001234567-24-000001",
        "filing_date": "2024-03-16",
        "document_url": "https://www.sec.gov/Archives/edgar/data/1234567/000123456724000001/f4.xml",
    }
    monkeypatch.setattr(form4_connector, "recent_form4_filings", lambda cik, limit=20, client=None: [filing])
    xml = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerCik>0001234567</issuerCik><issuerName>Acme Corp</issuerName><issuerTradingSymbol>ACME</issuerTradingSymbol></issuer>
  <reportingOwner><reportingOwnerId><rptOwnerCik>0001111111</rptOwnerCik><rptOwnerName>Jane CEO</rptOwnerName></reportingOwnerId>
  <reportingOwnerRelationship><isOfficer>true</isOfficer><officerTitle>CEO</officerTitle></reportingOwnerRelationship></reportingOwner>
  <nonDerivativeTable><nonDerivativeTransaction>
    <transactionDate><value>2024-03-15</value></transactionDate>
    <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>P</transactionCode></transactionCoding>
    <transactionAmounts><transactionShares><value>50000</value></transactionShares>
    <transactionPricePerShare><value>10.0</value></transactionPricePerShare>
    <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
  </nonDerivativeTransaction></nonDerivativeTable>
</ownershipDocument>"""
    result = insider_service.get_signals_for_ticker("ACME", fetcher=lambda f: xml)
    assert result["status"] == "ok"
    block = result["provenance"]
    assert block["source"] == "SEC EDGAR"
    assert block["source_kind"] == "official"
    assert block["coverage"] == "ok"
    assert block["source_url"].startswith("https://www.sec.gov/")
    datetime.fromisoformat(block["fetched_at"])


def test_market_indices_carry_unofficial_provenance(monkeypatch):
    """Contract: /api/market/indices labels Yahoo as unofficial, real fetch time."""
    from app.api.routes import market

    monkeypatch.setattr(market, "_cache", {"at": 0.0, "items": [], "fetched_at": None})
    monkeypatch.setattr(market, "_fetch_index", lambda client, symbol: {"price": 100.0, "change_pct": 0.1})

    class _Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(market.httpx, "Client", _Client)
    result = market.market_indices()
    block = result["provenance"]
    assert block["source_kind"] == "unofficial"
    assert "no oficial" in block["note"]
    assert block["coverage"] == "ok"
    first_fetch = block["fetched_at"]
    datetime.fromisoformat(first_fetch)

    # cached serve keeps the ORIGINAL fetch time, never a fresh fabrication
    result2 = market.market_indices()
    assert result2["provenance"]["fetched_at"] == first_fetch

    # partial coverage when some indices fail
    monkeypatch.setattr(market, "_cache", {"at": 0.0, "items": [], "fetched_at": None})
    monkeypatch.setattr(
        market, "_fetch_index",
        lambda client, symbol: {"price": 1.0, "change_pct": 0.0} if symbol == market._INDEXES[0]["symbol"] else None,
    )
    result3 = market.market_indices()
    assert result3["provenance"]["coverage"] == "partial"


def test_thesis_history_carries_computed_provenance():
    """Contract: thesis history exposes internal-computation provenance + data_as_of."""
    from fastapi.testclient import TestClient

    import main
    from app.seed import seed
    from tests.test_thesis_history_memo import TICKER, _clean, _seed_two_versions

    seed()  # igual que los tests hermanos de thesis history: crea la Company (ASTS)
    _clean()
    v1_id, v2_id = _seed_two_versions()
    response = TestClient(main.app).get(f"/api/thesis/{TICKER}/history")
    assert response.status_code == 200
    payload = response.json()
    block = payload["provenance"]
    assert block["source_kind"] == "internal"
    assert block["coverage"] == "ok"
    assert payload["data_as_of"] is not None
    datetime.fromisoformat(payload["data_as_of"])
    _clean()


def test_risk_dashboard_carries_computed_provenance(perf_db=None):
    """Contract: risk dashboard exposes data_as_of (stalest input) + provenance."""
    # reuse the perf fixture seeder indirectly: minimal synthetic portfolio
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.models  # noqa: F401
    from app.core.database import Base
    from app.models import Company, Portfolio, Position
    from app.services.risk_service import RiskService

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    company = Company(
        ticker="ACME", name="Acme", currency="USD", exchange="NASDAQ",
        sector="Tech", industry="Software", company_type="research_candidate",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    portfolio = Portfolio(name="main", base_currency="USD", is_default=True)
    db.add(portfolio)
    db.flush()
    db.add(Position(
        portfolio_id=portfolio.id, company_id=company.id, quantity=10,
        currency="USD", market_price=100, market_value=1000,
        market_value_native=1000,
        as_of=datetime(2026, 9, 20).date(),
    ))
    db.commit()
    result = RiskService().dashboard(db)
    block = result["provenance"]
    assert block["source_kind"] == "internal"
    assert result["data_as_of"] is not None
    assert "2026-09-20" in result["data_as_of"]
    db.close()
