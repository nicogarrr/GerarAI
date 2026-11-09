"""Informe tipo analista: datos de mercado y cifras reales por periodo.

Ingresos reales de Apple (tests/fixtures/aapl_ttm.json, SEC companyfacts): el
Q4 del ejercicio 2025 no tiene 10-Q y se deriva como FY − Q1 − Q2 − Q3 =
416.161 − 313.695 = 102.466 M$ (la cifra que Apple publicó para ese trimestre).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact, MarketPrice
from app.services.analyst_report import build_company_report

M = 1_000_000
aapl = json.loads((Path(__file__).parent / "fixtures" / "aapl_ttm.json").read_text("utf-8"))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker="AAPL", currency="USD"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency=currency,
        sector="S", industry="I", company_type="quality",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fact(db, company, metric, period, value, quarter, *, source="SEC", unit="USD", reported=True):
    db.add(FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit,
        period=period, fiscal_year=int(period[:4]) if quarter == "FY" else None,
        fiscal_quarter=quarter, source_type=source, is_reported=reported,
    ))


def _seed_apple_revenue(db, company):
    labels = ["Q1", "Q2", "Q3", "Q1", "Q2", "Q3"]
    for (_, end, val), label in zip(aapl["REVENUE_Q"], labels, strict=True):
        _fact(db, company, "revenue", f"{end}:{label}", val * M, label)
    for _, end, val in aapl["REVENUE_FY"]:
        _fact(db, company, "revenue", f"{end}:FY", val * M, "FY")


def test_revenue_by_year_and_quarter_with_derived_q4(db):
    company = _company(db)
    _seed_apple_revenue(db, company)
    db.commit()
    report = build_company_report(db, company, today=date(2026, 8, 1))
    annual = report["estimates"]["annual"]
    assert [row["period_end"] for row in annual] == [date(2025, 9, 27)]
    assert annual[0]["revenue"]["value"] == 416_161 * M
    quarterly = report["estimates"]["quarterly"]
    # Seis más recientes: Q2-Q3 FY25, el Q4 derivado y Q1-Q3 FY26.
    assert [row["fiscal_quarter"] for row in quarterly] == ["Q2", "Q3", "Q4", "Q1", "Q2", "Q3"]
    q4 = quarterly[2]
    assert q4["period_end"] == date(2025, 9, 27)
    assert q4["revenue"]["value"] == 102_466 * M
    assert q4["revenue"]["derived_q4"] is True and q4["revenue"]["reported"] is False
    assert quarterly[-1]["revenue"] == {"value": 109_417 * M, "unit": "USD", "source": "SEC",
                                        "reported": True, "basis": "reported", "derived_q4": False, "url": None}


def test_q4_ignores_previous_year_q4(db):
    """Forma de ASTS en SEC (CIK 1780312): el 10-K de 2024 trae un Q4 de 3 meses y el de
    2025 no. Q4 2025 = 70.918 − 718 − 1.156 − 14.739 = 54.305 miles de $."""
    company = _company(db, "ASTS")
    _fact(db, company, "revenue", "2024-12-31:Q4", 1_918_000, "Q4")
    for end, label, val in (("2025-03-31", "Q1", 718_000), ("2025-06-30", "Q2", 1_156_000), ("2025-09-30", "Q3", 14_739_000)):
        _fact(db, company, "revenue", f"{end}:{label}", val, label)
    _fact(db, company, "revenue", "2025-12-31:FY", 70_918_000, "FY")
    db.commit()
    quarterly = build_company_report(db, company, today=date(2026, 11, 8))["estimates"]["quarterly"]
    assert [row["fiscal_quarter"] for row in quarterly] == ["Q4", "Q1", "Q2", "Q3", "Q4"]
    assert quarterly[0]["revenue"]["derived_q4"] is False
    assert quarterly[-1]["revenue"]["value"] == 54_305_000 and quarterly[-1]["revenue"]["derived_q4"] is True


def test_ebitda_is_operating_income_plus_da_and_prefers_sec(db):
    company = _company(db)
    end = "2025-12-31"
    _fact(db, company, "operating_income", f"{end}:FY", -300 * M, "FY")
    _fact(db, company, "depreciation_amortization", f"{end}:FY", 50 * M, "FY")
    _fact(db, company, "ebitda", f"{end}:FY", -999 * M, "FY", source="FMP")
    _fact(db, company, "revenue", f"{end}:FY", 5 * M, "FY", source="FMP")
    _fact(db, company, "revenue", f"{end}:FY", 4 * M, "FY")
    _fact(db, company, "ebitda", "2024-12-31:FY", -100 * M, "FY", source="FMP")
    db.commit()
    annual = build_company_report(db, company, today=date(2026, 3, 1))["estimates"]["annual"]
    assert [row["period_end"] for row in annual] == [date(2024, 12, 31), date(2025, 12, 31)]
    latest = annual[1]
    assert latest["revenue"]["value"] == 4 * M and latest["revenue"]["source"] == "SEC"
    assert latest["ebitda"]["value"] == -250 * M
    assert latest["ebitda"]["basis"] == "operating_income_plus_da"
    # Sin resultado operativo ni D&A, el EBITDA de la fuente, con su nombre.
    assert annual[0]["ebitda"]["basis"] == "source_ebitda" and annual[0]["ebitda"]["source"] == "FMP"
    assert annual[0]["revenue"] is None


def _prices(db, company, closes, *, start=date(2026, 1, 2), volume=1_000, currency="USD"):
    from datetime import timedelta

    for i, close in enumerate(closes):
        db.add(MarketPrice(company_id=company.id, date=start + timedelta(days=i), open=close, high=close,
                           low=close, close=Decimal(str(close)), volume=volume + i, quote_currency=currency,
                           source="test"))


def test_market_cap_ev_and_average_volume(db):
    company = _company(db, "ASTS")
    _prices(db, company, [30 + i * 0.01 for i in range(80)])
    _fact(db, company, "shares_outstanding", "2026-09-30:Q3", 389.1 * M, "Q3")
    _fact(db, company, "shares_diluted", "2026-09-30:Q3", 380 * M, "Q3")
    _fact(db, company, "cash_and_equivalents", "2026-09-30:Q3", 1_200 * M, "Q3")
    _fact(db, company, "total_debt", "2026-09-30:Q3", 700 * M, "Q3")
    db.commit()
    market = build_company_report(db, company, today=date(2026, 11, 8))["market"]
    assert market["price_date"] == date(2026, 3, 22)
    assert market["price"] == pytest.approx(30.79)
    # 63 sesiones más recientes: volúmenes 1017..1079.
    assert market["avg_volume_sessions"] == 63 and market["avg_volume"] == 1048
    assert market["shares_outstanding"]["value"] == 389.1 * M
    assert market["shares_diluted"]["value"] == 380 * M
    assert market["market_cap"] == pytest.approx(30.79 * 389.1 * M)
    assert market["market_cap_basis"] == "shares_outstanding"
    assert market["enterprise_value"] == pytest.approx(30.79 * 389.1 * M + 700 * M - 1_200 * M)
    assert market["enterprise_value_reason"] is None


def test_ev_is_not_mixed_across_dates_or_currencies(db):
    company = _company(db, "XYZ")
    _prices(db, company, [10.0])
    _fact(db, company, "shares_outstanding", "2026-09-30:Q3", 100 * M, "Q3")
    _fact(db, company, "cash_and_equivalents", "2026-09-30:Q3", 10 * M, "Q3")
    _fact(db, company, "total_debt", "2026-06-30:Q2", 5 * M, "Q2")
    db.commit()
    market = build_company_report(db, company, today=date(2026, 11, 8))["market"]
    assert market["market_cap"] == pytest.approx(1_000 * M)
    assert market["enterprise_value"] is None
    assert market["enterprise_value_reason"] == "cash_debt_different_dates"

    other = _company(db, "EURX", currency="EUR")
    _prices(db, other, [10.0], currency="USD")
    _fact(db, other, "shares_outstanding", "2026-09-30:Q3", 100 * M, "Q3", unit="shares")
    _fact(db, other, "cash_and_equivalents", "2026-09-30:Q3", 10 * M, "Q3", unit="EUR")
    _fact(db, other, "total_debt", "2026-09-30:Q3", 5 * M, "Q3", unit="EUR")
    db.commit()
    market = build_company_report(db, other, today=date(2026, 11, 8))["market"]
    assert market["currency"] == "USD"
    assert market["enterprise_value"] is None and market["enterprise_value_reason"] == "currency_mismatch"


def test_empty_company_says_so(db):
    company = _company(db, "NEW")
    report = build_company_report(db, company, today=date(2026, 11, 8))
    assert report["estimates"] == {"annual": [], "quarterly": []}
    market = report["market"]
    assert market["price"] is None and market["market_cap"] is None and market["avg_volume"] is None
    assert market["enterprise_value_reason"] == "no_market_cap"


def test_endpoint_is_mounted_under_companies():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool

    from app.api.router import api_router
    from app.core.database import get_db

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    company = _company(db, "ASTS")
    _seed_apple_revenue(db, company)
    db.commit()
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    ok = client.get("/api/companies/ASTS/analyst-report")
    assert ok.status_code == 200
    body = ok.json()
    assert body["ticker"] == "ASTS" and body["version"] == "analyst-report-v1"
    assert body["estimates"]["annual"][0]["revenue"]["value"] == 416_161 * M
    assert client.get("/api/companies/NOPE/analyst-report").status_code == 404


@pytest.mark.parametrize("quote,price,unit,cash,debt", [
    ("GBp", 4255, "GBP", 10_000_000, 5_000_000),
    ("GBX", 4255, "GBP", 10_000_000, 5_000_000),
    ("GBP", 42.55, "GBp", 1_000_000_000, 500_000_000),
    ("USD", 42.55, "USD", 10_000_000, 5_000_000),
])
def test_market_minor_units_keep_quote_and_normalize_cap_ev(db, quote, price, unit, cash, debt):
    company = _company(db, "MINOR", currency=unit)
    _prices(db, company, [price], currency=quote)
    _fact(db, company, "shares_outstanding", "2026-09-30:Q3", M, "Q3", unit="shares")
    _fact(db, company, "cash_and_equivalents", "2026-09-30:Q3", cash, "Q3", unit=unit)
    _fact(db, company, "total_debt", "2026-09-30:Q3", debt, "Q3", unit=unit)
    db.commit()
    market = build_company_report(db, company, today=date(2026, 11, 8))["market"]
    expected_currency = "USD" if quote == "USD" else "GBP"
    assert market["price"] == pytest.approx(price)
    assert market["currency"] == quote
    assert market["cash"]["unit"] == unit and market["cash"]["value"] == cash
    assert market["total_debt"]["unit"] == unit and market["total_debt"]["value"] == debt
    assert market["market_cap_currency"] == expected_currency
    assert market["enterprise_value_currency"] == expected_currency
    assert market["market_cap"] == pytest.approx(42_550_000)
    assert market["enterprise_value"] == pytest.approx(37_550_000)
    assert market["enterprise_value_reason"] is None


def test_each_actual_links_to_its_filing(db):
    company = _company(db)
    company.cik = "0000320193"
    db.add(FinancialFact(
        company_id=company.id, metric="revenue", value=Decimal("416161000000"), unit="USD",
        period="2025-09-27:FY", fiscal_year=2025, fiscal_quarter="FY", source_type="SEC", is_reported=True,
        accession_number="0000320193-25-000079",
    ))
    db.commit()
    cell = build_company_report(db, company, today=date(2026, 8, 1))["estimates"]["annual"][0]["revenue"]
    assert cell["url"] == ("https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/"
                           "0000320193-25-000079-index.htm")
