"""Todo lo que trae el Flex se guarda crudo (raw_payload completo), se use o no todavia."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import IbkrRawRow, Portfolio, Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService

XML = """<FlexQueryResponse queryName="q" type="AF"><FlexStatements count="1">
<FlexStatement accountId="U1" fromDate="20250101" toDate="20251231" whenGenerated="20260101;120000">
  <CashReport><CashReportCurrency accountId="U1" currency="USD" endingCash="10" commissions="-1.5" withholdingTax="-3"/></CashReport>
  <OpenPositions>
    <OpenPosition accountId="U1" symbol="AAA" currency="USD" position="10" markPrice="11" positionValue="110" levelOfDetail="SUMMARY" reportDate="20251231"/>
    <Lot accountId="U1" symbol="AAA" currency="USD" openDateTime="20250102;093000" originatingTransactionID="t1" levelOfDetail="LOT"/>
  </OpenPositions>
  <Trades>
    <Trade accountId="U1" assetCategory="STK" subCategory="ETF" symbol="AAA" currency="USD" buySell="BUY" quantity="10" tradePrice="10" tradeDate="20250102" dateTime="20250102;093000" tradeID="t1" ibOrderID="o1" orderReference="ref-x" isin="US0000000001"/>
  </Trades>
  <CashTransactions><CashTransaction accountId="U1" type="Dividends" currency="USD" amount="5" dateTime="20250601;000000" transactionID="c1" symbol="AAA" code="Po"/></CashTransactions>
  <Transfers><Transfer accountId="U1" type="ACATS" direction="IN" date="20250105" transactionID="tr1" quantity="3" symbol="AAA" currency="USD"/></Transfers>
  <CorporateActions><CorporateAction accountId="U1" type="FS" symbol="AAA" currency="USD" dateTime="20250301;000000" transactionID="ca1" quantity="10"/></CorporateActions>
  <ConversionRates><ConversionRate reportDate="20251231" fromCurrency="USD" toCurrency="EUR" rate="0.85"/></ConversionRates>
  <FutureSection><FutureRow accountId="U1" newField="42"/></FutureSection>
  <EmptyThing/>
</FlexStatement></FlexStatements></FlexQueryResponse>"""


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    t = Tenant(external_id="raw-test", name="raw")
    s.add(t)
    s.flush()
    s.info["tenant_id"] = t.id
    s.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    s.flush()
    return s


def _rows(db):
    return db.scalars(select(IbkrRawRow)).all()


def test_every_section_row_is_stored_with_full_attributes_even_if_unused(db):
    result = IBKRImportService().import_flex_xml(db, XML)
    by_path = {}
    for r in _rows(db):
        by_path.setdefault(r.path, []).append(r)
    assert set(by_path) == {
        "CashReport/CashReportCurrency", "OpenPositions/OpenPosition", "OpenPositions/Lot",
        "Trades/Trade", "CashTransactions/CashTransaction", "Transfers/Transfer",
        "CorporateActions/CorporateAction", "ConversionRates/ConversionRate", "FutureSection/FutureRow",
    }
    trade = by_path["Trades/Trade"][0]
    assert trade.section == "Trades"
    assert trade.payload["orderReference"] == "ref-x" and trade.payload["ibOrderID"] == "o1"
    assert trade.payload["subCategory"] == "ETF" and trade.payload["dateTime"] == "20250102;093000"
    assert by_path["CashReport/CashReportCurrency"][0].payload["withholdingTax"] == "-3"
    assert by_path["ConversionRates/ConversionRate"][0].payload["rate"] == "0.85"
    assert by_path["OpenPositions/Lot"][0].payload["originatingTransactionID"] == "t1"
    assert by_path["FutureSection/FutureRow"][0].payload == {"accountId": "U1", "newField": "42"}
    assert all(r.account_id == "U1" for r in _rows(db) if "ConversionRate" not in r.path)
    assert result["raw_rows_stored"] == 9 and result["raw_rows_already_present"] == 0


def test_elements_without_attributes_are_not_rows(db):
    IBKRImportService().import_flex_xml(db, XML)
    paths = {r.path for r in _rows(db)}
    assert not any(p in {"EmptyThing", "Trades", "CashReport"} for p in paths)


def test_reimport_is_idempotent(db):
    svc = IBKRImportService()
    svc.import_flex_xml(db, XML)
    again = svc.import_flex_xml(db, XML)
    assert again["raw_rows_stored"] == 0 and again["raw_rows_already_present"] == 9
    assert db.scalar(select(func.count(IbkrRawRow.id))) == 9


def test_changed_values_are_kept_as_a_new_row_not_overwritten(db):
    svc = IBKRImportService()
    svc.import_flex_xml(db, XML)
    svc.import_flex_xml(db, XML.replace('rate="0.85"', 'rate="0.86"'))
    rates = [r.payload["rate"] for r in _rows(db) if r.path == "ConversionRates/ConversionRate"]
    assert sorted(rates) == ["0.85", "0.86"]


def test_existing_import_results_do_not_change(db):
    result = IBKRImportService().import_flex_xml(db, XML)
    assert result["trades_imported"] == 1
    assert [t.external_id for t in db.scalars(select(Transaction)).all() if t.external_id == "t1"] == ["t1"]


def test_trades_only_backfill_also_stores_raw_and_dry_run_writes_nothing(db):
    IBKRImportService().import_flex_xml(db, XML, trades_only=True, dry_run=True)
    assert db.scalar(select(func.count(IbkrRawRow.id))) == 0
    r = IBKRImportService().import_flex_xml(db, XML, trades_only=True)
    assert r["raw_rows_stored"] == 9


def test_same_row_in_two_tenants_is_stored_for_each(db):
    IBKRImportService().import_flex_xml(db, XML)
    other = Tenant(external_id="raw-test-2", name="raw2")
    db.add(other)
    db.flush()
    db.info["tenant_id"] = other.id
    db.add(Portfolio(name="Main2", base_currency="EUR", is_default=True))
    db.flush()
    r = IBKRImportService().import_flex_xml(db, XML)
    assert r["raw_rows_stored"] == 9
    assert db.scalar(select(func.count(IbkrRawRow.id)).where(IbkrRawRow.tenant_id == other.id)) == 9


def test_migration_0096_upgrade_downgrade_idempotent():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0096_ibkr_raw_rows.py"
    spec = importlib.util.spec_from_file_location("m0096", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "0096_ibkr_raw_rows" and len(mod.revision) <= 32
    assert mod.down_revision == "0095_fx_conversions"
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("create table tenants(id integer primary key)"))
        with Operations.context(MigrationContext.configure(conn)):
            mod.upgrade()
            mod.upgrade()
            assert "ibkr_raw_rows" in sa.inspect(conn).get_table_names()
            mod.downgrade()
            assert "ibkr_raw_rows" not in sa.inspect(conn).get_table_names()


def test_flex_doc_lists_sections_and_has_no_token_placeholder():
    doc = (Path(__file__).resolve().parents[2] / "docs" / "ibkr" / "FLEX_QUERY_CAMPOS.md").read_text()
    for section in ("Trades", "CashTransactions", "ConversionRates", "CashReport", "OpenPositions",
                    "Transfers", "CorporateActions", "Trade Time", "Level of Detail"):
        assert section in doc
    import re
    from urllib.parse import urlparse

    urls = re.findall(r"https?://[^\s)]+", doc)
    assert any(urlparse(url).hostname in {"ibkrguides.com", "www.ibkrguides.com"} for url in urls)
    assert "nunca" in doc.lower()
