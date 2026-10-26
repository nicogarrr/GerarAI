"""IBKR CSV es-ES decimals and Flex cash rows without an amount (synthetic QA fixtures)."""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from app.core.database import Base
from app.models import CashBalance, Transaction
from app.services.ibkr_import_service import IBKRImportError, IBKRImportService, _csv_decimal
from tests.test_ibkr_import import _tenant_session

CSV = (
    "symbol,action,quantity,price,date,fees,currency\n"
    'QAZ1,buy,"1,5","12,50",2026-01-05,"0,35",EUR\n'
    'QAZ2,buy,10,"1.234,56",2026-01-06,0,EUR\n'
    "QAZ3,buy,10,100.25,2026-01-07,0,USD\n"
)


def _flex(row):
    return (
        '<FlexQueryResponse queryName="QA" type="AF"><FlexStatements count="1">'
        '<FlexStatement accountId="QA000" fromDate="2026-10-01" toDate="2026-10-23">'
        f"<CashReport>{row}</CashReport></FlexStatement></FlexStatements></FlexQueryResponse>"
    )


@pytest.mark.parametrize(
    "raw,expected",
    [("12,50", "12.50"), ("1,5", "1.5"), ("0,35", "0.35"), ("1.234,56", "1234.56"),
     ("1,234.56", "1234.56"), ("100.25", "100.25"), ("32.725", "32.725"), ("10", "10")],
)
def test_csv_decimal_values(raw, expected):
    assert _csv_decimal(raw) == Decimal(expected)


def test_csv_decimal_rejects_garbage_not_zero():
    with pytest.raises(IBKRImportError):
        _csv_decimal("abc")


def test_csv_import_reads_decimal_comma_correctly_and_keeps_usd():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = _tenant_session(engine)
    result = IBKRImportService().import_ibkr_csv(db, CSV)
    rows = {t.ticker if hasattr(t, "ticker") else t.id: t for t in db.query(Transaction).all()}
    got = sorted((t.quantity, t.price, t.fees, t.currency) for t in db.query(Transaction).all())
    assert got == sorted([
        (Decimal("1.5"), Decimal("12.50"), Decimal("0.35"), "EUR"),
        (Decimal("10"), Decimal("1234.56"), Decimal("0"), "EUR"),
        (Decimal("10"), Decimal("100.25"), Decimal("0"), "USD"),
    ])
    assert result["trades_imported"] == 3
    # replay is idempotent
    again = IBKRImportService().import_ibkr_csv(db, CSV)
    assert again["trades_imported"] == 0 and db.query(Transaction).count() == 3
    db.close()


def test_flex_cash_row_without_amount_does_not_overwrite_balance():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = _tenant_session(engine)
    svc = IBKRImportService()
    svc.import_flex_xml(db, _flex('<CashReportCurrency currency="EUR" endingCash="100.00" reportDate="2026-09-25"/>'))
    svc.import_flex_xml(db, _flex('<CashReportCurrency currency="EUR"/>'))
    cash = db.query(CashBalance).filter(CashBalance.currency == "EUR").one()
    assert cash.balance == Decimal("100.00")
    assert str(cash.as_of) == "2026-09-25"
    db.close()
