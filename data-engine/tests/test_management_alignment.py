"""Synthetic XBRL-shaped evidence. Company labels are scenarios, not financial claims."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Company,
    FinancialFact,
    InsiderFiling,
    InsiderTransaction,
    ManagementAlignmentSnapshot,
    Tenant,
)
from app.services import management_alignment as m
from app.services.connectors.form4 import parse_form4_xml
from app.services.insider_persistence import persist_filing

TODAY = date(2026, 11, 11)
COMPANY = NS(cik="0000320193", currency="USD", ticker="AAPL")


def fact(metric, amount, year=2025, **overrides):
    return NS(id=1, metric=metric, value=Decimal(str(amount)), unit="shares" if metric.startswith("shares_") else "USD",
              period=f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter="FY", filed=date(year + 1, 2, 1),
              source_type="SEC", is_reported=True, accession_number=f"0000320193-{str(year + 1)[2:]}-000001", source=None,
              **{}) if not overrides else NS(**{**vars(fact(metric, amount, year)), **overrides})


def full_facts():
    return [fact(metric, value, year) for year, share in [(2024, 100), (2025, 108.2)] for metric, value in [
        ("shares_outstanding", share), ("stock_based_compensation", 120), ("revenue", 1000),
        ("common_stock_repurchased", 0), ("common_stock_issued", 10),
        ("operating_cash_flow", 300), ("capital_expenditure", -100)]]


def test_complete_mega_cap_dilution_sbc_and_true_zero():
    rows = m.dilution_years(full_facts(), COMPANY, [], TODAY)
    row = rows[-1]
    assert row["shares_change_pct"]["value"] == 8.2
    assert row["sbc_revenue_pct"]["value"] == 12.0
    assert row["sbc_fcf_pct"]["value"] == 60.0
    assert len(row["sbc_fcf_pct"]["sources"]) == 3
    assert row["repurchases"]["value"] == 0
    assert row["change_label"] == "Dilución neta anual"
    assert row["repurchases_label"] == "Recompras (bruto)"
    assert row["sbc"]["url"].endswith("0000320193-26-000001-index.htm")
    assert row["sbc"]["filed"] == "2026-02-01"


def test_growth_missing_repurchases_is_never_zero_and_no_fake_net():
    facts = [f for f in full_facts() if f.metric not in {"common_stock_repurchased", "operating_cash_flow"}]
    row = m.dilution_years(facts, NS(**{**vars(COMPANY), "ticker": "ASTS"}), [], TODAY)[-1]
    assert row["repurchases"] is None
    assert row["change_label"] == "Variación de acciones"
    assert row["sbc_fcf_pct"]["value"] is None
    assert any("no equivale a cero" in w for w in row["warnings"])


def test_unsupported_european_is_empty_not_invented_foreign_cause():
    assert m.dilution_years([], NS(cik=None, currency="EUR", ticker="AENA.MC"), [], TODAY) == []


def test_fallback_dei_uses_same_annual_accession_and_diluted_is_distinct():
    annual = fact("revenue", 1000)
    dei = fact("shares_outstanding", 123, fiscal_year=None, fiscal_quarter=None, period="2026-01-20:DEI")
    wrong_quarter = fact("shares_outstanding", 999, fiscal_year=None, fiscal_quarter=None, period="2026-05-20:DEI", accession_number="0000320193-26-000002")
    row = m.dilution_years([annual, dei, wrong_quarter, fact("shares_diluted", 130)], COMPANY, [], TODAY)[-1]
    assert row["shares"]["value"] == 123
    assert row["year"] == 2025 and row["share_basis"] == "dei"
    row = m.dilution_years([annual, fact("shares_diluted", 130)], COMPANY, [], TODAY)[-1]
    assert row["shares"]["value"] == 130 and row["share_basis"] == "shares_diluted"
    assert any("promedio ponderado" in w for w in row["warnings"])
    row = m.dilution_years([annual, dei, fact("shares_outstanding", 140)], COMPANY, [], TODAY)[-1]
    assert row["shares"]["value"] == 140


@pytest.mark.parametrize("overrides", [
    {"filed": None}, {"filed": date(2027, 1, 1)}, {"accession_number": None}, {"value": Decimal("NaN")},
    {"is_reported": False}, {"source_type": "seed"}, {"unit": "EUR"},
    {"period": "garbage"}, {"period": "2027-12-31:FY"}, {"fiscal_quarter": "Q3"},
    {"source_type": "ESEF", "source": NS(source_url="javascript:alert(1)")},
    {"source_type": "CNMV", "source": NS(source_url="http://[")},
])
def test_unverifiable_evidence_never_publishes_number(overrides):
    assert m._evidence(fact("stock_based_compensation", 100, **overrides), COMPANY, TODAY) is None


def test_local_source_url_and_ratio_missing_or_invalid_denominator():
    e = m._evidence(fact("revenue", 10, source_type="ESEF", source=NS(source_url="https://example.com/filing")), COMPANY, TODAY)
    assert e["url"] == "https://example.com/filing"
    assert m._ratio(None, e)["value"] is None
    assert m._ratio(e, {**e, "unit": "EUR"})["value"] is None
    assert m._ratio(e, {**e, "value": 0})["value"] is None
    assert m._ratio(e, {**e, "date": "2024-12-31"})["value"] is None
    assert m._round(1.25) == 1.3 and m._round(-1.25) == -1.3


def test_split_and_basis_change_and_gaps_do_not_publish_fake_dilution():
    rows = m.dilution_years(full_facts(), COMPANY, [NS(effective_date=date(2025, 5, 1))], TODAY)
    assert rows[-1]["shares_change_pct"]["value"] is None
    assert "split" in rows[-1]["shares_change_pct"]["reason"]
    rows = m.dilution_years([fact("shares_outstanding", 10, 2024), fact("shares_diluted", 11)], COMPANY, [], TODAY)
    assert rows[-1]["shares_change_pct"]["value"] is None
    rows = m.dilution_years([fact("shares_outstanding", 10, 2023), fact("shares_outstanding", 11)], COMPANY, [], TODAY)
    assert rows[-1]["shares_change_pct"]["value"] is None


def test_last_five_restatement_and_abrupt_warning_no_hiding():
    facts = [fact("shares_outstanding", 100, year) for year in range(2018, 2026)]
    facts += [fact("shares_outstanding", 300, filed=date(2026, 3, 1)), fact("stock_based_compensation", -10)]
    row = m.dilution_years(facts, COMPANY, [], TODAY)
    assert len(row) == 5 and row[0]["year"] == 2021
    assert row[-1]["shares"]["value"] == 300 and row[-1]["shares_change_pct"]["value"] == 200
    assert len(row[-1]["warnings"]) >= 2
    assert row[-1]["sbc"]["value"] == -10
    row = m.dilution_years([fact("shares_outstanding", -1), fact("common_stock_repurchased", -10)], COMPANY, [], TODAY)[0]
    assert any("no positivo" in w for w in row["warnings"])


def xml(flag=None, code="S", when="2026-10-01"):
    mark = "" if flag is None else f"<aff10b5One>{flag}</aff10b5One>"
    return f'''<ownershipDocument><issuer><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
    <nonDerivativeTable><nonDerivativeTransaction><transactionDate><value>{when}</value></transactionDate>
    <transactionCoding><transactionCode>{code}</transactionCode>{mark}</transactionCoding>
    <transactionAmounts><transactionShares><value>10</value></transactionShares><transactionPricePerShare><value>10</value></transactionPricePerShare></transactionAmounts>
    </nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>'''


@pytest.mark.parametrize("flag,expected", [("0", False), ("1", True), ("true", True), ("false", False), (None, None), ("unexpected", None)])
def test_xml_four_serializations_and_unknown(flag, expected):
    tx = parse_form4_xml(xml(flag))["transactions"][0]
    assert tx["alignment_10b5_1"] is expected
    assert tx["rule_10b5_1"] is bool(expected)  # legacy contract unchanged


def tx(code="S", plan=None, **kwargs):
    return NS(**{"code": code, "is_derivative": False, "tx_date": "2026-10-01", "value": 100.0,
                 "shares": 10.0, "price": 10.0, "data_quality": {"alignment_10b5_1": plan},
                 "rule_10b5_1": False, "source_url": "https://example.com/form4.xml", "accession_number": "A", "form": "4", **kwargs})


def test_windows_exclude_nonmarket_derivative_and_planned_sale_from_discretionary():
    rows = [(tx("P"), None), (tx(plan=True, value=600), None), (tx(plan=False), None)]
    rows += [(tx(code, plan=False, value=99999), None) for code in ["A", "M", "F", "G"]]
    rows += [(tx("S", is_derivative=True, value=99999), None)]
    for w in m.insider_windows(rows, TODAY):
        assert w["net_value"] == -600
        assert w["discretionary_net_value"] == 0
        assert len(w["groups"]["planned_sales"]) == 1
        assert len(w["groups"]["unplanned_sales"]) == 1
        assert not w["groups"]["unknown_sales"]


def test_unknown_plan_not_discretionary_legacy_false_and_missing_value_not_zero():
    row = tx(data_quality={}, value=None, shares=None)
    w = m.insider_windows([(row, None)], TODAY)[-1]
    assert len(w["groups"]["unknown_sales"]) == 1
    assert w["discretionary_net_value"] is None and w["net_value"] is None
    w = m.insider_windows([(tx(value=None), None)], TODAY)[-1]
    assert w["net_value"] == -100 and w["discretionary_net_value"] is None


def test_window_edges_calendar_months_missing_dates_bad_links_amendments_and_invalid_amounts():
    rows = [(tx("P", tx_date="2026-05-11"), None), (tx(tx_date="2026-05-10"), None),
            (tx(tx_date="2025-11-11"), None), (tx(tx_date="2025-11-10"), None),
            (tx(tx_date="2026-11-12"), None), (tx(tx_date=None), "2026-11-11"), (tx(tx_date="bad"), None)]
    six, twelve = m.insider_windows(rows, TODAY)
    assert len(six["groups"]["buys"]) == 1 and len(six["groups"]["unknown_sales"]) == 1
    assert len(twelve["groups"]["unknown_sales"]) == 3
    assert six["warnings"]
    assert m._months_before(date(2026, 8, 31), 6) == date(2026, 2, 28)
    for mutation in [{"source_url": None}, {"form": "4/A"}, {"form": "5/A"}]:
        w = m.insider_windows([(tx(**mutation), None)], TODAY)[0]
        assert w["status"] == "sin_datos" and w["net_value"] is None and w["warnings"]
    for value in [float("nan"), float("inf"), -1]:
        w = m.insider_windows([(tx(value=value), None)], TODAY)[0]
        assert w["net_value"] is None and w["warnings"]
        assert w["groups"]["unknown_sales"][0]["reported_value"] is not None
    assert m.insider_windows([], TODAY)[0]["status"] == "sin_datos"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_snapshot_read_is_precomputed_degrades_and_is_tenant_scoped(db):
    db.add_all([Tenant(id=1, external_id="one"), Tenant(id=2, external_id="two")]); db.flush()
    company = Company(ticker="AAPL", name="Apple", cik=COMPANY.cik, currency="USD", exchange="NASDAQ", company_type="holding", valuation_model="unassigned")
    db.add(company); db.flush()
    db.info["tenant_id"] = 1
    assert m.read_alignment(db, company)["status"] == "pendiente"
    record = m.recompute_alignment(db, company, today=TODAY)
    assert record.tenant_id == 1 and record.payload["years"] == []
    assert "persistida" in record.payload["dilution_reason"]
    assert m.read_alignment(db, company, today=TODAY)["stale"] is False
    assert m.read_alignment(db, company, today=date(2026, 11, 14))["stale"] is True
    m.recompute_alignment(db, company, today=TODAY)
    assert len(list(db.scalars(select(ManagementAlignmentSnapshot)))) == 1
    db.info["tenant_id"] = 2
    assert m.read_alignment(db, company)["status"] == "pendiente"
    row2 = m.recompute_alignment(db, company, today=TODAY)
    row2.version = 0; db.flush()
    assert m.read_alignment(db, company)["status"] == "pendiente"


def test_real_persistence_keeps_new_flag_unknown_and_legacy_boolean(db):
    for i, flag in enumerate([None, "0", "1", "true", "false"]):
        filing = {"accession_number": f"0000320193-26-{i:06d}", "form": "4", "filing_date": "2026-10-02", "document_url": "https://example.com/form4.xml"}
        parsed = parse_form4_xml(xml(flag))
        persist_filing(db, filing, parsed)
        persist_filing(db, filing, parsed)
    rows = list(db.scalars(select(InsiderTransaction).order_by(InsiderTransaction.id)))
    assert [r.data_quality["alignment_10b5_1"] for r in rows] == [None, False, True, True, False]
    assert [r.rule_10b5_1 for r in rows] == [False, False, True, True, False]
    # Existing record with old parser metadata receives only new evidence on normal reingestion.
    rows[2].data_quality = {}; db.commit()
    persist_filing(db, {"accession_number": "0000320193-26-000002", "form": "4"}, parse_form4_xml(xml("1")))
    assert rows[2].data_quality["alignment_10b5_1"] is True
    assert len(list(db.scalars(select(InsiderFiling)))) == 5


def test_migration_round_trip(db):
    import importlib
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    spec = importlib.util.spec_from_file_location("alignment_migration", Path(__file__).parents[1] / "alembic/versions/0135_management_alignment.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = db.connection()
    previous_op = migration.op
    migration.op = Operations(MigrationContext.configure(connection))
    try:
        migration.upgrade()  # create_all already made it: no duplicate table
        migration.downgrade()
        assert "management_alignment_snapshots" not in inspect(connection).get_table_names()
        migration.downgrade()  # absent is harmless
        migration.upgrade()
        assert "management_alignment_snapshots" in inspect(connection).get_table_names()
        assert {c["name"] for c in inspect(connection).get_columns("management_alignment_snapshots")} == {c.name for c in ManagementAlignmentSnapshot.__table__.columns}
    finally:
        migration.op = previous_op


def test_job_and_endpoint_use_persisted_snapshot_only(db, monkeypatch):
    from app.api.routes import companies as routes
    from app.services import earnings_dates_service
    from app.workers import dramatiq_app as worker
    company = Company(ticker="AAPL", name="Apple", cik=COMPANY.cik, currency="USD", exchange="NASDAQ", company_type="holding", valuation_model="unassigned")
    db.add(company); db.flush()
    calls = []
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    monkeypatch.setattr(worker.recompute_management_alignment, "send", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(routes, "resolve_company", lambda _db, ticker: company if ticker == "AAPL" else None)
    assert routes.company_management_alignment("AAPL", db)["status"] == "pendiente"
    assert calls == [{"tenant_id": None, "company_id": company.id}]
    def fail(**kwargs):
        raise ConnectionError("queue unavailable")
    monkeypatch.setattr(worker.recompute_management_alignment, "send", fail)
    assert "No se ha podido encolar" in routes.company_management_alignment("AAPL", db)["reason"]
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        routes.company_management_alignment("UNKNOWN", db)
    assert e.value.status_code == 404
    for f in full_facts():
        db.add(FinancialFact(company_id=company.id, **{k: v for k, v in vars(f).items() if k not in {"id", "source"}}))
    db.flush()
    # The worker's close is tested but does not close the shared fixture session early.
    closed = []
    monkeypatch.setattr(db, "close", lambda: closed.append(True))
    monkeypatch.setattr(worker, "_session", lambda *args: db)
    monkeypatch.setattr(earnings_dates_service, "followed_companies", lambda _db: {"AAPL": {"company": company}})
    assert worker.recompute_management_alignment.fn(company_id=company.id)["companies"] == 1
    assert worker.recompute_management_alignment.fn()["companies"] == 1
    assert len(closed) == 2
    result = routes.company_management_alignment("AAPL", db)
    assert result["status"] == "ok" and result["years"][-1]["shares_change_pct"]["value"] == 8.2
    monkeypatch.setattr(worker, "_handle_actor_error", lambda *args, **kwargs: {"status": "error"})
    from app.services import management_alignment
    monkeypatch.setattr(management_alignment, "recompute_alignment", lambda *args: (_ for _ in ()).throw(RuntimeError("bad snapshot")))
    assert worker.recompute_management_alignment.fn(company_id=company.id)["status"] == "error"
    assert len(closed) == 3


@pytest.mark.parametrize("ticker", ["AAPL", "ASTS", "AENA"])
def test_companyfacts_fixture_through_existing_ingestion_then_precompute(db, monkeypatch, ticker):
    import asyncio
    import json
    from pathlib import Path

    from app.services import financial_ingestion_service as ingestion
    fixture = json.loads((Path(__file__).parent / "fixtures/management_alignment" / f"{ticker.lower()}.json").read_text())
    class FakeSEC:
        async def cik_for_ticker(self, *args, **kwargs):
            return fixture.get("cik")
        async def annual_report_anchors(self, cik):
            return {f"{cik}-{str(y+1)[2:]}-000001": f"{y}-12-31" for y in [2024, 2025]}
        async def company_facts(self, cik):
            return fixture
        async def index_accessions(self, cik):
            return set(await self.annual_report_anchors(cik))
    async def empty_free_data(*args):
        return {"status": "unavailable", "recent_filings": [], "macro": None}
    company = Company(ticker=ticker, name=ticker, exchange="NASDAQ" if ticker != "AENA" else "BME", currency="USD" if ticker != "AENA" else "EUR", company_type="holding", valuation_model="unassigned")
    db.add(company); db.commit()
    monkeypatch.setattr(ingestion, "SECClient", FakeSEC)
    monkeypatch.setattr(ingestion, "_free_data_snapshot", empty_free_data)
    if ticker == "AENA":
        with pytest.raises(RuntimeError, match="Sin CIK"):
            asyncio.run(ingestion.FinancialIngestionService().refresh_from_sec(db=db, company=company))
    else:
        asyncio.run(ingestion.FinancialIngestionService().refresh_from_sec(db=db, company=company))
    snapshot = m.recompute_alignment(db, company, today=TODAY).payload
    if ticker == "AENA":
        assert snapshot["years"] == [] and snapshot["dilution_reason"]
    else:
        row = snapshot["years"][-1]
        assert row["shares_change_pct"]["value"] == 8.2
        assert row["sbc_revenue_pct"]["value"] == (12.0 if ticker == "AAPL" else 80.0)
        assert row["sbc_fcf_pct"]["value"] == (60.0 if ticker == "AAPL" else 400.0)
        assert row["repurchases"] is None if ticker == "ASTS" else row["repurchases"]["value"] == 0
        assert row["sbc"]["filed"] == "2026-02-01"


def test_dei_cover_anchors_to_latest_annual_close_not_restatement_comparative(db):
    current = fact("revenue", 1000)
    comparative = fact("revenue", 900, 2024, accession_number=current.accession_number)
    dei = fact("shares_outstanding", 123, fiscal_year=None, fiscal_quarter=None, period="2026-01-20:DEI")
    years = m.dilution_years([current, comparative, dei], COMPANY, [], TODAY)
    assert next(row for row in years if row["year"] == 2025)["shares"]["value"] == 123
    assert next(row for row in years if row["year"] == 2024)["shares"] is None
    # A cover after an arbitrary old comparative cannot silently become its annual balance.
    years = m.dilution_years([comparative, dei], COMPANY, [], TODAY)
    assert years[0]["shares"] is None
