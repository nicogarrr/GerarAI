"""Flex Query con fechas dd/MM/yyyy (formato elegible en IBKR, natural en España).

IBKR deja configurar el formato de fecha de cada Flex Query. Con dd/MM/yyyy el
importador (que solo conocía MM/dd/yyyy) fechaba la compra del 05/03/2026 el 3
de mayo y el dividendo del 02/04/2026 el 4 de febrero, sin aviso, y omitía la
compra del 15/03/2026 por «fecha no reconocida». El orden se decide ahora por
fichero, con la misma regla que el CSV: un número > 12 manda; sin evidencia,
MM/dd (el formato por defecto de IBKR, sin cambios).
"""
from datetime import date

import pytest
from sqlalchemy import create_engine

from app.core.database import Base
from app.models import Transaction
from app.services.ibkr_import_service import (
    IBKRImportError,
    IBKRImportService,
    _date,
    validate_flex_xml,
)
from tests.test_ibkr_import import _tenant_session


def _xml(rows: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<FlexQueryResponse queryName="t"><FlexStatements><FlexStatement accountId="U1">'
        f"{rows}</FlexStatement></FlexStatements></FlexQueryResponse>"
    )


DAY_FIRST = _xml(
    '<Trade symbol="AAPL" tradeID="T1" buySell="BUY" quantity="10" tradePrice="150" '
    'ibCommission="1" tradeDate="05/03/2026" currency="USD"/>'
    '<Trade symbol="AAPL" tradeID="T2" buySell="BUY" quantity="1" tradePrice="150" '
    'ibCommission="1" tradeDate="15/03/2026" currency="USD"/>'
    '<CashTransaction type="Dividends" trxID="D1" amount="15.5" dateTime="02/04/2026;101500" '
    'currency="USD"/>'
)


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return _tenant_session(engine)


def _dates(db):
    return {t.external_id: t.trade_date for t in db.query(Transaction).all()}


def test_day_first_flex_validates():
    assert validate_flex_xml(DAY_FIRST) == []


def test_day_first_flex_imports_every_row_on_its_real_date():
    db = _db()
    result = IBKRImportService().import_flex_xml(db, DAY_FIRST)
    assert result["rows_skipped"] == 0
    assert _dates(db) == {
        "T1": date(2026, 3, 5),
        "T2": date(2026, 3, 15),
        "D1": date(2026, 4, 2),
    }
    db.close()


def test_default_month_first_flex_is_unchanged():
    db = _db()
    IBKRImportService().import_flex_xml(
        db,
        _xml(
            '<Trade symbol="AAPL" tradeID="T1" buySell="BUY" quantity="1" tradePrice="1" '
            'ibCommission="0" tradeDate="05/03/2026" currency="USD"/>'
            '<Trade symbol="AAPL" tradeID="T2" buySell="BUY" quantity="1" tradePrice="1" '
            'ibCommission="0" tradeDate="12/31/2025" currency="USD"/>'
        ),
    )
    assert _dates(db) == {"T1": date(2026, 5, 3), "T2": date(2025, 12, 31)}
    db.close()


def test_two_digit_year_and_month_name_formats():
    db = _db()
    IBKRImportService().import_flex_xml(
        db,
        _xml(
            '<Trade symbol="AAPL" tradeID="T1" buySell="BUY" quantity="1" tradePrice="1" '
            'ibCommission="0" tradeDate="25/03/26" currency="USD"/>'
            '<Trade symbol="AAPL" tradeID="T2" buySell="BUY" quantity="1" tradePrice="1" '
            'ibCommission="0" tradeDate="04/03/26" currency="USD"/>'
            '<Trade symbol="AAPL" tradeID="T3" buySell="BUY" quantity="1" tradePrice="1" '
            'ibCommission="0" tradeDate="06-Mar-26" currency="USD"/>'
        ),
    )
    assert _dates(db) == {
        "T1": date(2026, 3, 25),
        "T2": date(2026, 3, 4),
        "T3": date(2026, 3, 6),
    }
    db.close()


def test_mixed_orders_reject_the_flex_before_writing():
    mixed = _xml(
        '<Trade symbol="AAPL" tradeID="T1" buySell="BUY" quantity="1" tradePrice="1" '
        'ibCommission="0" tradeDate="25/03/2026" currency="USD"/>'
        '<Trade symbol="AAPL" tradeID="T2" buySell="BUY" quantity="1" tradePrice="1" '
        'ibCommission="0" tradeDate="03/25/2026" currency="USD"/>'
    )
    errors = validate_flex_xml(mixed)
    assert len(errors) == 1 and "mezclan" in errors[0]
    db = _db()
    with pytest.raises(IBKRImportError):
        IBKRImportService().import_flex_xml(db, mixed)
    assert db.query(Transaction).count() == 0
    db.close()


def test_the_flex_order_does_not_leak_outside_the_import():
    db = _db()
    IBKRImportService().import_flex_xml(db, DAY_FIRST)
    db.close()
    assert _date("05/03/2026") == date(2026, 5, 3)
