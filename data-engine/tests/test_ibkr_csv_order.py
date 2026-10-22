"""Un CSV con la venta ANTES de la compra (export mas nuevo primero) no debe perder la venta."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService

NEWEST_FIRST = """symbol,action,quantity,price,date,fees,currency
ZZTEST,sell,6,7,2026-01-05,0,USD
ZZTEST,buy,10,5,2026-01-02,0,USD
"""

SAME_DAY_SELL_FIRST = """symbol,action,quantity,price,date,fees,currency
ZZSAME,sell,4,7,2026-01-05,0,USD
ZZSAME,buy,4,6,2026-01-05,0,USD
"""


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="csv-order-test", name="csv order")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def _actions(db):
    return sorted(db.scalars(select(Transaction.action)).all())


def test_newest_first_csv_keeps_the_sell():
    db = _session()
    result = IBKRImportService().import_ibkr_csv(db, NEWEST_FIRST)
    assert result["rows_skipped"] == 0, result["row_errors"]
    assert result["trades_imported"] == 2
    assert _actions(db) == ["buy", "sell"]


def test_same_day_round_trip_with_sell_first_in_file():
    db = _session()
    result = IBKRImportService().import_ibkr_csv(db, SAME_DAY_SELL_FIRST)
    assert result["rows_skipped"] == 0, result["row_errors"]
    assert _actions(db) == ["buy", "sell"]
