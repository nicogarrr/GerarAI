"""Flex Trades CASH (EUR.USD) -> fx_conversions -> libro de divisas. XML sintetico."""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Portfolio, Company, FXRate, FxConversion, Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService, parse_fx_trade
from app.services.tax_report_service import TaxReportService
from xml.etree import ElementTree as ET


def _xml(*trades: str) -> str:
    return ("<FlexQueryResponse><FlexStatements count='1'><FlexStatement accountId='U1' fromDate='20250101' toDate='20251231'>"
            "<Trades>" + "".join(trades) + "</Trades></FlexStatement></FlexStatements></FlexQueryResponse>")


FX_BUY = ("<Trade assetCategory='CASH' symbol='EUR.USD' buySell='BUY' quantity='900' tradePrice='1.1111' "
          "proceeds='-1000' currency='USD' tradeDate='20250301' tradeID='fx1'/>")
FX_SELL = ("<Trade assetCategory='CASH' symbol='EUR.USD' buySell='SELL' quantity='-400' tradePrice='1.1' "
           "proceeds='440' currency='USD' tradeDate='20250302' tradeID='fx2'/>")
STK = ("<Trade assetCategory='STK' symbol='AAA' buySell='BUY' quantity='10' tradePrice='100' "
       "currency='USD' tradeDate='20250105' tradeID='s1'/>")


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    tenant = Tenant(external_id="fx-test", name="fx")
    session.add(tenant)
    session.flush()
    session.info["tenant_id"] = tenant.id
    session.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    session.flush()
    return session


def test_parse_buy_eur_usd_disposes_usd():
    r = parse_fx_trade(ET.fromstring(FX_BUY))
    assert (r["disposed_currency"], r["disposed_amount"], r["acquired_currency"], r["acquired_amount"]) == ("USD", D("1000"), "EUR", D("900"))


def test_parse_sell_eur_usd_disposes_eur_and_is_not_usd_to_eur():
    r = parse_fx_trade(ET.fromstring(FX_SELL))
    assert (r["disposed_currency"], r["acquired_currency"], r["acquired_amount"]) == ("EUR", "USD", D("440"))


@pytest.mark.parametrize("bad", [
    "<Trade assetCategory='CASH' symbol='EURUSD' buySell='BUY' quantity='1' proceeds='-1' tradeDate='20250301'/>",
    "<Trade assetCategory='CASH' symbol='EUR.USD' quantity='1' proceeds='-1' tradeDate='20250301'/>",
    "<Trade assetCategory='CASH' symbol='EUR.USD' buySell='BUY' quantity='1' tradeDate='20250301'/>",
    "<Trade assetCategory='CASH' symbol='EUR.USD' buySell='BUY' quantity='x' proceeds='-1' tradeDate='20250301'/>",
    "<Trade assetCategory='CASH' symbol='EUR.USD' buySell='BUY' quantity='1' proceeds='-1'/>",
])
def test_parse_missing_data_returns_none(bad):
    assert parse_fx_trade(ET.fromstring(bad)) is None


def test_import_routes_cash_trades_to_fx_table_not_stock_ledger(db):
    result = IBKRImportService().import_flex_xml(db, _xml(STK, FX_BUY, FX_SELL))
    assert result["fx_conversions_imported"] == 2
    assert [t.external_id for t in db.scalars(select(Transaction)).all()] == ["s1"]
    assert db.scalars(select(Company).where(Company.ticker == "EUR.USD")).first() is None
    assert len(db.scalars(select(FxConversion)).all()) == 2


def test_reimport_is_idempotent_and_bad_rows_are_counted(db):
    svc = IBKRImportService()
    bad = "<Trade assetCategory='CASH' symbol='EUR.USD' buySell='BUY' quantity='1' tradeDate='20250301' tradeID='bad'/>"
    svc.import_flex_xml(db, _xml(FX_BUY))
    r = svc.import_flex_xml(db, _xml(FX_BUY, bad))
    assert r["fx_conversions_imported"] == 0 and r["fx_conversions_skipped"] == 1
    assert len(db.scalars(select(FxConversion)).all()) == 1


def _rates(db):
    for day, rate in [(date(2025, 1, 5), "0.90"), (date(2025, 3, 1), "0.95")]:
        db.add(FXRate(base_currency="EUR", quote_currency="USD", rate_date=day, rate=D(rate), source="ECB"))
    db.commit()


def _tx(db, action, qty, price, day, cur="USD"):
    company = db.scalars(select(Company).where(Company.ticker == "AAA")).first()
    if company is None:
        company = Company(ticker="AAA", name="AAA", exchange="NASDAQ", currency="USD", sector="S", industry="I", company_type="holding", valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[], domicile_country="US")
        db.add(company)
        db.flush()
    db.add(Transaction(company_id=company.id, trade_date=day, action=action, quantity=D(qty), price=D(price), fees=D(0), currency=cur, raw_payload={}))
    db.commit()


def test_report_without_conversions_is_not_computed(db):
    _rates(db)
    s = TaxReportService().compute_report(db, 2025)["summary"]
    assert s["currency_ledger_status"] == "not_computed" and s["currency_ledger_gain_base"] is None


def test_report_with_stored_conversion_but_unmodeled_buy_is_incomplete_not_a_number(db):
    _rates(db)
    _tx(db, "buy", 10, 100, date(2025, 1, 2))
    _tx(db, "sell", 10, 120, date(2025, 1, 5))
    IBKRImportService().import_flex_xml(db, _xml(FX_BUY))
    s = TaxReportService().compute_report(db, 2025, fx_opening_complete=True)["summary"]
    assert s["currency_ledger_status"] == "incomplete" and s["currency_ledger_gain_base"] is None
    assert "sin modelar" in s["currency_ledger_reason"]


def test_report_missing_opening_balance_is_incomplete(db):
    _rates(db)
    _tx(db, "sell", 10, 120, date(2025, 1, 5))
    IBKRImportService().import_flex_xml(db, _xml(FX_BUY))
    s = TaxReportService().compute_report(db, 2025)["summary"]
    assert s["currency_ledger_status"] == "incomplete"
    assert "saldo" in s["currency_ledger_reason"]


def test_ledger_value_when_only_sale_and_conversion_exist(db):
    _rates(db)
    # venta sin compra previa en BD: over_sell -> proceeds_base conocido igual; usamos conversion explicita
    from app.services.currency_ledger import Conversion
    _tx(db, "sell", 10, 100, date(2025, 1, 5))  # 1000 USD x 0.90 = 900 EUR
    conv = [Conversion(date(2025, 3, 1), D(1000), D("0.95"), "x")]
    s = TaxReportService().compute_report(db, 2025, fx_conversions=conv, fx_opening_complete=True)["summary"]
    # la venta sin compra en BD cuenta como flujo no modelado? no: es sell. Ganancia = 950 - 900
    assert s["currency_ledger_gain_base"] == 50.0 and s["currency_ledger_status"] == "computed"


def test_backfill_trades_only_also_stores_fx_conversions(db):
    r = IBKRImportService().import_flex_xml(db, _xml(STK, FX_BUY), trades_only=True)
    assert r["fx_conversions_imported"] == 1 and r["non_stock_skipped"] == 1
    assert len(db.scalars(select(FxConversion)).all()) == 1
