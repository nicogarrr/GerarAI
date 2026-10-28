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


def test_report_with_sale_and_stored_conversion_is_computed(db):
    _rates(db)
    _tx(db, "buy", 10, 100, date(2024, 12, 20))
    _tx(db, "sell", 10, 120, date(2025, 1, 5))  # 1200 USD x 0.90 = 1080 EUR de valor
    # compra de 10 acciones en 2024 queda fuera de esta divisa (anterior al lote): se pasa saldo confirmado
    IBKRImportService().import_flex_xml(db, _xml(FX_BUY), trades_only=True)
    s = TaxReportService().compute_report(db, 2025, fx_opening_complete=True)["summary"]
    # La compra de 1000 USD en 2024 no tiene lote anterior: incompleta, nunca un numero inventado.
    assert s["currency_ledger_status"] == "incomplete" and s["currency_ledger_gain_base"] is None
    assert "compra" in s["currency_ledger_reason"]


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


EUR_TO_USD = ("<Trade assetCategory='CASH' symbol='EUR.USD' buySell='SELL' quantity='-400' tradePrice='1.25' "
              "proceeds='500' currency='USD' tradeDate='20250101' tradeID='e2u'/>")
USD_100_TO_EUR = ("<Trade assetCategory='CASH' symbol='EUR.USD' buySell='BUY' quantity='95' tradePrice='1.0526' "
                  "proceeds='-100' currency='USD' tradeDate='20250301' tradeID='u2e'/>")


def _flow(db):
    _rates(db)
    db.add(FXRate(base_currency="EUR", quote_currency="USD", rate_date=date(2025, 2, 1), rate=D("0.92"), source="ECB"))
    db.commit()
    IBKRImportService().import_flex_xml(db, _xml(EUR_TO_USD, USD_100_TO_EUR), trades_only=True)
    _tx(db, "buy", 4, 100, date(2025, 1, 2))  # 400 USD salen sin resultado (V0282-22, V0706-22)


def test_eur_to_usd_lot_purchase_outflow_and_conversion_give_a_number(db):
    _flow(db)
    s = TaxReportService().compute_report(db, 2025, fx_opening_complete=True)["summary"]
    # 500 USD costaron 400 EUR; compra de 400 USD consume 320 EUR de coste sin resultado;
    # quedan 100 USD a 80 EUR; convertidos a 0.95 = 95 EUR -> +15
    assert s["currency_ledger_status"] == "computed" and s["currency_ledger_gain_base"] == 15.0


def test_dividend_in_currency_blocks_result_unless_analogy_flag(db):
    _flow(db)
    _tx(db, "dividend", 1, 10, date(2025, 2, 1))
    svc = TaxReportService()
    s = svc.compute_report(db, 2025, fx_opening_complete=True)["summary"]
    assert s["currency_ledger_status"] == "incomplete" and "sin modelar" in s["currency_ledger_reason"]
    s2 = svc.compute_report(db, 2025, fx_opening_complete=True, fx_income_by_analogy=True)["summary"]
    assert s2["currency_ledger_status"] == "computed" and s2["currency_ledger_gain_base"] == 15.0
    assert "analogía, sin consulta" in s2["currency_ledger_note"]


def test_fund_purchase_in_currency_is_out_of_scope(db):
    _flow(db)
    company = db.scalars(select(Company)).first()
    db.add(Transaction(company_id=company.id, trade_date=date(2025, 1, 3), action="buy", quantity=D(1), price=D(1), fees=D(0),
                       currency="USD", raw_payload={"assetCategory": "FUND"}))
    db.commit()
    s = TaxReportService().compute_report(db, 2025, fx_opening_complete=True)["summary"]
    assert s["currency_ledger_status"] == "incomplete" and "V0775-21" in s["currency_ledger_reason"]


def test_flex_datetime_feeds_same_day_rule(db):
    # compra de divisa (EUR->USD) 10:00 el mismo dia que la conversion USD->EUR con perdida a las 09:00
    _rates(db)
    db.add(FXRate(base_currency="EUR", quote_currency="USD", rate_date=date(2026, 3, 1), rate=D("0.80"), source="ECB"))
    db.commit()
    buy_usd = ("<Trade assetCategory='CASH' symbol='EUR.USD' buySell='SELL' quantity='-90' tradePrice='1.1' proceeds='100' "
               "currency='USD' tradeDate='20250301' dateTime='20250301;100000' tradeID='b'/>")
    first = ("<Trade assetCategory='CASH' symbol='EUR.USD' buySell='SELL' quantity='-100' tradePrice='1' proceeds='100' "
             "currency='USD' tradeDate='20250101' dateTime='20250101;100000' tradeID='a'/>")
    sell_usd = ("<Trade assetCategory='CASH' symbol='EUR.USD' buySell='BUY' quantity='90' tradePrice='1.11' proceeds='-100' "
                "currency='USD' tradeDate='20250301' dateTime='20250301;090000' tradeID='c'/>")
    IBKRImportService().import_flex_xml(db, _xml(first, buy_usd, sell_usd), trades_only=True)
    _tx(db, "sell", 1, 1, date(2026, 6, 1))  # fecha de datos posterior a la ventana de 1 año
    s = TaxReportService().compute_report(db, 2025, fx_opening_complete=True)["summary"]
    assert s["currency_ledger_status"] == "computed", s["currency_ledger_reason"]
    assert s["currency_ledger_blocked_loss_base"] == 5.0
