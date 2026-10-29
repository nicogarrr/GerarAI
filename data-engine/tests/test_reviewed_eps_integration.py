"""Exact PDF adjustments are usable without rewriting reported ESEF rows."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes.watchlist import watchlist_metrics
from app.models.entities import Base, Company, Document, FinancialFact, MarketPrice, Tenant
from app.services.derived_market_cap_service import _shares_outstanding
from app.services.esef_fact_quarantine import EBRO_LEI, LOG_LEI
from app.services.reviewed_eps_adjustments import REVIEW_ID, REVIEWED, SOURCE_TYPE
from app.services.screener_fundamentals import load_screener_ratios
from app.services.ttm_service import build_company_ttm
from app.valuation.financial_snapshot import _facts_for_metric


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id=1, external_id="reviewed-test"))
        db.commit()
        db.info["tenant_id"] = 1
        yield db
    engine.dispose()


def seed(db, lei=EBRO_LEI):
    ticker = "EBRO" if lei == EBRO_LEI else "LOG"
    company = Company(
        ticker=ticker,
        name=ticker,
        exchange="BME",
        currency="EUR",
        sector="S",
        industry="I",
        company_type="standard",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    original = Document(
        company_id=company.id, tenant_id=1, title="ESEF original", source_type="ESEF", metadata_={"lei": lei}
    )
    db.add(original)
    db.flush()
    year = 2025
    period = "2025-01-01:FY" if lei == EBRO_LEI else "2025-09-30:FY"
    raw = FinancialFact(
        company_id=company.id,
        tenant_id=1,
        metric="eps_diluted",
        value=Decimal("1351" if lei == EBRO_LEI else "2130"),
        unit="EUR/share",
        period=period,
        fiscal_year=year,
        fiscal_quarter="FY",
        source_type="ESEF",
        is_reported=True,
        source_id=original.id,
    )
    db.add(raw)
    adjusted = []
    for (owner, period, value), (url, checksum, page) in REVIEWED.items():
        if owner != lei:
            continue
        doc = Document(
            company_id=company.id,
            tenant_id=1,
            title="Reviewed issuer PDF",
            source_type=SOURCE_TYPE,
            source_url=url,
            checksum=checksum,
            metadata_={"lei": lei, "review_id": REVIEW_ID, "pdf_page": page},
        )
        db.add(doc)
        db.flush()
        row = FinancialFact(
            company_id=company.id,
            tenant_id=1,
            metric="eps_diluted",
            value=value,
            unit="EUR/share",
            period=period,
            fiscal_year=int(period[:4]),
            fiscal_quarter="FY",
            source_type=SOURCE_TYPE,
            is_reported=False,
            is_adjusted=True,
            source_id=doc.id,
        )
        db.add(row)
        adjusted.append(row)
    db.add(
        FinancialFact(
            company_id=company.id,
            tenant_id=1,
            metric="market_cap",
            value=100,
            unit="EUR",
            period=date.today().isoformat(),
            source_type="FMP",
            is_reported=True,
        )
    )
    db.add(
        MarketPrice(
            company_id=company.id,
            date=date.today(),
            open=20,
            high=20,
            low=20,
            close=20,
            source="exchange",
            quote_currency="EUR",
        )
    )
    db.commit()
    return company, raw, adjusted


@pytest.mark.parametrize("lei,eps,year", [(EBRO_LEI, "1.351", 2024), (LOG_LEI, "2.13", 2025)])
def test_watchlist_pdf_provenance_correct_fy_and_raw_unchanged(db, lei, eps, year):
    company, raw, rows = seed(db, lei)
    original = (raw.value, raw.period, raw.fiscal_year, raw.source_id, raw.is_reported)
    result = watchlist_metrics(company.ticker, db)
    assert result["per"] == pytest.approx(20 / float(eps))
    note = " ".join(result["sources"])
    assert f"FY{year}" in note and "dato ajustado, PDF anual revisado:" in note
    assert "https://" in note
    db.refresh(raw)
    assert (raw.value, raw.period, raw.fiscal_year, raw.source_id, raw.is_reported) == original
    assert len(db.scalars(select(FinancialFact).where(FinancialFact.metric == "eps_diluted")).all()) == 3


def test_ttm_adjusted_not_official_and_snapshot_filter(db):
    company, raw, rows = seed(db)
    payload = build_company_ttm(db, company)
    eps = next(m for m in payload["metrics"] if m["metric"] == "eps_diluted")
    assert eps["value"] == Decimal("1.351")
    assert eps["provenance"] == "INFERIDO" and eps["period_end"] == date(2024, 12, 31)
    assert "PDF anual" in eps["note"]
    assert raw not in _facts_for_metric(db, company.id, "eps_diluted")
    rows[0].source.checksum = "invalid"
    db.commit()
    assert rows[0] not in _facts_for_metric(db, company.id, "eps_diluted")


def test_unreviewed_adjustment_cannot_restore_per(db):
    company, raw, rows = seed(db)
    for row in rows:
        row.source.checksum = "invalid"
    db.commit()
    result = watchlist_metrics(company.ticker, db)
    assert result["per"] is None
    assert "cuarentena" in " ".join(result["sources"])
    eps = next(m for m in build_company_ttm(db, company)["metrics"] if m["metric"] == "eps_diluted")
    assert eps["value"] is None


def test_screener_and_share_derivation_do_not_upgrade_adjusted_to_reported(db):
    company, raw, rows = seed(db)
    ratios = load_screener_ratios(db, {company.ticker})
    assert ratios[company.ticker]["pe"] is None
    assert _shares_outstanding(db, company) is None

