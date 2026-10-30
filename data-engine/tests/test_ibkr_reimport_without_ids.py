"""Reimportar un Flex cuyas filas no traen tradeID/transactionID no duplica nada.

Si la query Flex no incluye esas columnas, cada sync volvia a insertar la compra
(5 AAPL pasaban a 10) o el dividendo (dos cobros de 12 en vez de uno).
"""

from sqlalchemy import create_engine

from app.core.database import Base
from app.models import Transaction
from app.services.ibkr_import_service import IBKRImportService
from tests.test_ibkr_import import _tenant_session

BUY = (
    '<Trade accountId="U1" symbol="AAPL" assetCategory="STK" currency="USD" buySell="BUY" '
    'quantity="5" tradePrice="100" tradeDate="20261001" ibCommission="-1"/>'
)
DIVIDEND = (
    '<CashTransaction accountId="U1" symbol="AAPL" currency="USD" type="Dividends" '
    'amount="12" dateTime="20261002" description="AAPL CASH DIVIDEND USD 0.25"/>'
)


def _xml(*rows):
    return (
        '<?xml version="1.0"?><FlexQueryResponse><FlexStatements><FlexStatement accountId="U1">'
        + "".join(rows)
        + "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return _tenant_session(engine)


def _rows(db):
    return sorted((t.action, t.quantity, t.price) for t in db.query(Transaction).all())


def test_trade_without_id_is_not_duplicated_on_reimport():
    db = _session()
    for _ in range(2):
        IBKRImportService().import_flex_xml(db, _xml(f"<Trades>{BUY}</Trades>"))
    assert [(a, int(q)) for a, q, _ in _rows(db)] == [("buy", 5)]


def test_two_identical_fills_in_one_file_stay_two():
    db = _session()
    for _ in range(2):
        IBKRImportService().import_flex_xml(db, _xml(f"<Trades>{BUY}{BUY}</Trades>"))
    assert [(a, int(q)) for a, q, _ in _rows(db)] == [("buy", 5), ("buy", 5)]


def test_dividend_without_id_is_not_duplicated_on_reimport():
    db = _session()
    xml = _xml(f"<Trades>{BUY}</Trades><CashTransactions>{DIVIDEND}</CashTransactions>")
    for _ in range(2):
        IBKRImportService().import_flex_xml(db, xml)
    assert len([r for r in _rows(db) if r[0] != "buy"]) == 1


def test_rows_stored_before_without_id_are_adopted_not_duplicated():
    db = _session()
    xml = _xml(f"<Trades>{BUY}</Trades><CashTransactions>{DIVIDEND}</CashTransactions>")
    IBKRImportService().import_flex_xml(db, xml)
    for t in db.query(Transaction).all():  # como las guardaba la version anterior
        t.external_id = None
    db.commit()
    IBKRImportService().import_flex_xml(db, xml)
    assert len(_rows(db)) == 2
    assert all(t.external_id for t in db.query(Transaction).all())
