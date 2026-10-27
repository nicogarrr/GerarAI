from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, CorporateAction, Document, FinancialFact
from app.models.entities import Base
from app.services.share_capital_service import build_share_capital


@pytest.fixture
def setup():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "tenant-test"
        company = Company(ticker="TEST", name="Test", currency="USD", exchange="NASDAQ", company_type="holding", valuation_model="unassigned")
        db.add(company)
        db.flush()
        doc = Document(company_id=company.id, title="SEC", source_type="SEC",
                       source_url="https://www.sec.gov/test",
                       published_at=datetime(2026, 1, 30, tzinfo=UTC),
                       metadata_={"capital_fact_provenance": {
                           "shares_outstanding": {"2025-12-31:FY": {"filed": "2026-01-30", "concept": "CommonStockSharesOutstanding"}}
                       }})
        db.add(doc)
        db.flush()
        yield db, company, doc


def fact(setup, metric, value, period, unit="shares", **kwargs):
    db, company, doc = setup
    row = FinancialFact(company_id=company.id, source_id=doc.id, source_type="SEC",
                        metric=metric, value=Decimal(str(value)), unit=unit, period=period,
                        fiscal_quarter=period.split(":")[-1], is_reported=True, **kwargs)
    db.add(row)
    db.flush()
    return row


def test_net_change_is_not_buybacks_and_weighted_shares_are_excluded(setup):
    db, company, _ = setup
    a = fact(setup, "shares_outstanding", 100, "2024-12-31:FY")
    fact(setup, "shares_outstanding", 90, "2025-12-31:FY")
    fact(setup, "shares_diluted", 99, "2025-12-31:FY")
    data = build_share_capital(db, company)
    assert data["series"][1]["net_change_pct"] == -10
    assert data["series"][0]["fact_id"] == a.id
    assert data["series"][1]["reported_on"] == "2026-01-30"
    assert data["annual_flows"] == []
    assert "buybacks" not in data["series"][1]


def test_split_suppresses_comparison(setup):
    db, company, _ = setup
    fact(setup, "shares_outstanding", 100, "2024-12-31:FY")
    fact(setup, "shares_outstanding", 400, "2025-12-31:FY")
    db.add(CorporateAction(company_id=company.id, action_type="split", effective_date=date(2025, 6, 1), ratio=4))
    db.flush()
    last = build_share_capital(db, company)["series"][-1]
    assert last["net_change_pct"] is None
    assert last["split_between_dates"] is True


@pytest.mark.parametrize("before,after", [(100, 670), (100, 374), (400, 100)])
def test_abrupt_jump_without_registered_split_is_not_comparable(setup, before, after):
    """Un split sin registrar en CorporateAction no debe salir como +570%."""
    db, company, _ = setup
    fact(setup, "shares_outstanding", before, "2024-12-31:FY")
    fact(setup, "shares_outstanding", after, "2025-12-31:FY")
    last = build_share_capital(db, company)["series"][-1]
    assert last["abrupt_jump"] is True
    assert last["net_change_pct"] is None and last["net_change"] is None
    assert last["change_status"] == "SIN_DATOS"
    assert last["split_between_dates"] is False


def test_moderate_change_stays_derived(setup):
    db, company, _ = setup
    fact(setup, "shares_outstanding", 100, "2024-12-31:FY")
    fact(setup, "shares_outstanding", 125, "2025-12-31:FY")
    last = build_share_capital(db, company)["series"][-1]
    assert last["abrupt_jump"] is False and last["net_change_pct"] == 25


def test_only_annual_flows_no_ytd_sum_no_missing_to_zero(setup):
    db, company, _ = setup
    fact(setup, "common_stock_repurchased", 200, "2025-12-31:FY", unit="USD")
    fact(setup, "common_stock_repurchased", 100, "2025-09-30:Q3", unit="USD")
    fact(setup, "shares_repurchased", 0, "2025-12-31:FY")
    flows = build_share_capital(db, company)["annual_flows"]
    assert len(flows) == 1
    assert flows[0]["common_stock_repurchased"]["value"] == 200
    assert flows[0]["shares_repurchased"]["value"] == 0
    assert "common_stock_issued" not in flows[0]


@pytest.mark.parametrize("reason", ["seed", "unreported", "no_source", "bad_unit", "future", "zero", "negative", "bad_period"])
def test_reject_unverified_balances(setup, reason):
    db, company, doc = setup
    row = fact(setup, "shares_outstanding", 100, "2025-12-31:FY")
    if reason == "seed": row.source_type = "seed"
    if reason == "unreported": row.is_reported = False
    if reason == "no_source": doc.source_url = None
    if reason == "bad_unit": row.unit = "USD"
    if reason == "future": row.period = "2099-12-31:FY"
    if reason == "zero": row.value = Decimal(0)
    if reason == "negative": row.value = Decimal(-1)
    if reason == "bad_period": row.period = "FY2025"
    db.flush()
    assert build_share_capital(db, company)["status"] == "SIN_DATOS"


def test_tenant_isolation(setup):
    db, company, _ = setup
    fact(setup, "shares_outstanding", 100, "2025-12-31:FY")
    db.info["tenant_id"] = "other-tenant"
    assert build_share_capital(db, company)["series"] == []


def test_latest_restatement_wins_and_dates_deduplicate(setup):
    db, company, _ = setup
    fact(setup, "shares_outstanding", 100, "2025-12-31:Q4")
    fact(setup, "shares_outstanding", 110, "2025-12-31:FY")
    data = build_share_capital(db, company)
    assert len(data["series"]) == 1
    assert data["series"][0]["value"] == 110


def test_sec_map_contains_exact_capital_concepts():
    from app.services.financial_ingestion_service import SEC_METRIC_MAP
    mapping = {metric: (concepts, unit) for metric, concepts, unit in SEC_METRIC_MAP}
    # Alias documentados: el valor de recompras/emision tambien sale del
    # disclosure de la memoria (StockRepurchasedDuringPeriodValue /
    # StockIssuedDuringPeriodValueNewIssues); _collapse_aliases deja un
    # ganador por periodo (filed mas reciente). 4.171 y 10.821 CIKs mas
    # cubiertos, medido sobre el parquet DenyTranDFW/edgar_xbrl_companyfacts.
    assert mapping["common_stock_repurchased"] == (
        ["PaymentsForRepurchaseOfCommonStock", "StockRepurchasedDuringPeriodValue"], "USD")
    assert mapping["common_stock_issued"] == (
        ["ProceedsFromIssuanceOfCommonStock", "StockIssuedDuringPeriodValueNewIssues"], "USD")
    assert mapping["shares_repurchased"] == (["StockRepurchasedDuringPeriodShares"], "shares")


def test_ingestion_capital_flows_duration_and_provenance(setup, monkeypatch):
    import asyncio

    from app.services import financial_ingestion_service as ingestion

    class FakeSEC:
        async def cik_for_ticker(self, ticker):
            return "0009999999"

        async def annual_report_anchors(self, cik):
            return {"2025-k": "2025-12-31"}

        async def company_facts(self, cik):
            entries = [
                {"accn": "2025-k", "fp": "FY", "form": "10-K", "start": "2025-01-01",
                 "end": "2025-12-31", "val": 250, "filed": "2026-02-01"},
                {"accn": "2025-k", "fp": "FY", "form": "10-K", "start": "2025-10-01",
                 "end": "2025-12-31", "val": 9999, "filed": "2026-02-02"},
                {"accn": "2025-k", "fp": "FY", "form": "10-K",
                 "end": "2025-12-31", "val": 7777, "filed": "2026-02-03"},
            ]
            return {"facts": {"us-gaap": {
                # #2384: sin Assets/Liabilities/Equity la divisa de reporte es
                # desconocida y los flujos en USD no se guardan.
                "Assets": {"units": {"USD": entries}},
                "PaymentsForRepurchaseOfCommonStock": {"units": {"USD": entries}},
                "ProceedsFromIssuanceOfCommonStock": {"units": {"USD": entries}},
                "CommonStockSharesOutstanding": {"units": {"shares": [{
                    "accn": "2025-k", "fp": "FY", "form": "10-K", "end": "2025-12-31",
                    "val": 1000, "filed": "2026-02-01",
                }]}},
            }}}

    db, company, _ = setup
    monkeypatch.setattr(ingestion, "SECClient", FakeSEC)
    asyncio.run(ingestion.FinancialIngestionService().refresh_from_sec(db=db, company=company))
    data = build_share_capital(db, company)
    assert data["annual_flows"][0]["common_stock_repurchased"]["value"] == 250
    assert data["annual_flows"][0]["common_stock_issued"]["value"] == 250
    assert data["annual_flows"][0]["common_stock_issued"]["reported_on"] == "2026-02-01"
    assert data["series"][0]["value"] == 1000
    assert data["series"][0]["concept"] == "CommonStockSharesOutstanding"
