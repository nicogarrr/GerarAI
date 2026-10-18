"""Backfill historico por rangos: solo Trades, idempotente, sin tocar posiciones ni caja."""
import asyncio
from datetime import date

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import CashBalance, Company, Position, Tenant, Transaction
from app.services.ibkr_backfill_service import backfill_trades, split_ranges
from app.services.ibkr_import_service import IBKRImportService

XML = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="test"><FlexStatements><FlexStatement accountId="U1">
  <OpenPosition symbol="AAPL" position="99" markPrice="1" positionValue="99" costBasisPrice="1" currency="USD" reportDate="2026-01-01"/>
  <CashReport currency="USD" endingCash="5" reportDate="2026-01-01"/>
  <Trade assetCategory="STK" symbol="AAPL" tradeID="T1" buySell="BUY" quantity="10" tradePrice="150" ibCommission="1" tradeDate="2026-03-02" currency="USD"/>
  <Trade assetCategory="STK" symbol="NEWCO" tradeID="T2" buySell="BUY" quantity="3" tradePrice="10" ibCommission="1" tradeDate="2026-03-03" currency="USD"/>
  <Trade assetCategory="CASH" symbol="EUR.USD" tradeID="T3" buySell="BUY" quantity="1000" tradePrice="1.1" tradeDate="2026-03-03" currency="USD"/>
  <CashTransaction type="Dividends" trxID="D1" amount="15.5" dateTime="2026-07-01" currency="USD"/>
</FlexStatement></FlexStatements></FlexQueryResponse>"""


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="bf", name="bf")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    db.add(Company(ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD", sector="Tech",
                   industry="Tech", company_type="stock", valuation_model="x", special_sources=[],
                   special_risks=[], factor_tags=[]))
    db.commit()
    return db


def _counts(db):
    return (
        db.scalar(select(func.count(Transaction.id))),
        db.scalar(select(func.count(Position.id))),
        db.scalar(select(func.count(CashBalance.id))),
        db.scalar(select(func.count(Company.id))),
    )


def test_trades_only_imports_stock_trades_without_touching_positions_cash_or_new_companies():
    db = _db()
    r = IBKRImportService().import_flex_xml(db, XML, trades_only=True, only_existing_companies=True)
    assert r["status"] == "imported"
    assert r["trades_imported"] == 1
    assert r["non_stock_skipped"] == 1
    assert r["skipped_unknown_tickers"] == {"NEWCO": 1}
    assert _counts(db) == (1, 0, 0, 1)  # una operacion; ni posiciones, ni caja, ni emisores nuevos


def test_trades_only_is_idempotent_and_dry_run_writes_nothing():
    db = _db()
    dry = IBKRImportService().import_flex_xml(db, XML, trades_only=True, dry_run=True, only_existing_companies=True)
    assert dry["status"] == "dry_run" and dry["trades_imported"] == 1
    assert _counts(db) == (0, 0, 0, 1)
    IBKRImportService().import_flex_xml(db, XML, trades_only=True, only_existing_companies=True)
    again = IBKRImportService().import_flex_xml(db, XML, trades_only=True, only_existing_companies=True)
    assert again["trades_imported"] == 0 and again["trades_already_present"] == 1
    assert _counts(db)[0] == 1


def test_can_create_new_companies_when_allowed():
    db = _db()
    r = IBKRImportService().import_flex_xml(db, XML, trades_only=True, only_existing_companies=False)
    assert r["trades_imported"] == 2
    assert _counts(db)[3] == 2


def test_split_ranges_stays_under_the_ibkr_limit():
    ranges = split_ranges(date(2024, 1, 1), date(2026, 10, 16))
    assert ranges[0][0] == date(2024, 1, 1) and ranges[-1][1] == date(2026, 10, 16)
    assert all((e - s).days + 1 <= 360 for s, e in ranges)
    assert all(ranges[i][1] < ranges[i + 1][0] for i in range(len(ranges) - 1))


def test_backfill_calls_client_per_range():
    class Fake:
        def __init__(self):
            self.calls = []

        async def fetch_range_xml(self, fd, td):
            self.calls.append((fd, td))
            return XML

    db = _db()
    fake = Fake()
    out = asyncio.run(backfill_trades(db, date(2025, 1, 1), date(2026, 3, 31), dry_run=True, client=fake))
    assert len(out) == len(fake.calls) == 2
    assert fake.calls[0][0] == "20250101"
    assert _counts(db)[0] == 0
