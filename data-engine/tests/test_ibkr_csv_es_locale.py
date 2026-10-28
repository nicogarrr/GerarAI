"""CSV de IBKR re-guardado con Excel en español: coma decimal y fechas dd/mm.

Abrir el CSV de IBKR en Excel es-ES y guardarlo produce «;» como separador,
coma decimal y fechas dd/mm/aaaa. Desde #2685 el fichero se acepta, pero:

* un precio con 3 decimales («32,725», habitual en IBKR) se leía como 32725
  (x1000: la regla «coma + 3 cifras = miles» de los CSV en-US);
* «05/03/2026» se leía como 3 de mayo (mm/dd) en vez de 5 de marzo, sin
  ningún aviso: fecha, tipo de cambio y regla de los 2 meses falseados;
* «15/03/2026» se rechazaba como fecha no reconocida.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from app.core.database import Base
from app.models import Transaction
from app.services.ibkr_import_service import (
    IBKRImportError,
    IBKRImportService,
    validate_ibkr_csv,
)
from tests.test_ibkr_import import _tenant_session

EXCEL_ES = (
    "symbol;action;quantity;price;date;fees;currency\n"
    "ZETA;buy;10;32,725;05/03/2026;1,25;USD\n"
    "ZETB;buy;2;101,5;15/03/2026;0;EUR\n"
)


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return _tenant_session(engine)


def _rows(db):
    return sorted(
        (t.price, t.trade_date, t.fees) for t in db.query(Transaction).all()
    )


def test_excel_es_csv_validates():
    assert validate_ibkr_csv(EXCEL_ES) == []


def test_excel_es_three_decimal_price_and_day_first_dates():
    db = _db()
    result = IBKRImportService().import_ibkr_csv(db, EXCEL_ES)
    assert result["trades_imported"] == 2
    assert _rows(db) == [
        (Decimal("32.725"), date(2026, 3, 5), Decimal("1.25")),
        (Decimal("101.5"), date(2026, 3, 15), Decimal("0")),
    ]
    db.close()


def test_semicolon_file_all_ambiguous_dates_are_day_first():
    db = _db()
    IBKRImportService().import_ibkr_csv(
        db, "symbol;action;quantity;price;date\nZETA;buy;1;10;01/02/2026\n"
    )
    assert _rows(db)[0][1] == date(2026, 2, 1)
    db.close()


def test_comma_file_keeps_us_month_first_and_us_thousands():
    db = _db()
    IBKRImportService().import_ibkr_csv(
        db,
        'symbol,action,quantity,price,date\nZETA,buy,1,"1,234",01/02/2026\n'
        "ZETB,buy,1,10,12/31/2025\n",
    )
    assert _rows(db) == [
        (Decimal("10"), date(2025, 12, 31), Decimal("0")),
        (Decimal("1234"), date(2026, 1, 2), Decimal("0")),
    ]
    db.close()


def test_comma_file_with_day_over_12_first_is_day_first():
    db = _db()
    IBKRImportService().import_ibkr_csv(
        db, "symbol,action,quantity,price,date\nA,buy,1,10,25/03/2026\nB,buy,1,10,04/03/2026\n"
    )
    assert sorted(t.trade_date for t in db.query(Transaction).all()) == [
        date(2026, 3, 4), date(2026, 3, 25)
    ]
    db.close()


def test_mixed_date_orders_reject_the_file_instead_of_guessing():
    mixed = "symbol;action;quantity;price;date\nA;buy;1;10;25/03/2026\nB;buy;1;10;03/25/2026\n"
    errors = validate_ibkr_csv(mixed)
    assert len(errors) == 1 and "mezclan" in errors[0]
    db = _db()
    with pytest.raises(IBKRImportError):
        IBKRImportService().import_ibkr_csv(db, mixed)
    assert db.query(Transaction).count() == 0
    db.close()


def test_reimport_after_fix_blocks_rows_imported_with_the_old_reading():
    """Un fichero importado con la lectura vieja (32725, 3 de mayo) no se duplica."""
    from app.services import ibkr_import_service as svc

    db = _db()
    old_decimal, old_day_first = svc._csv_decimal, svc._csv_slash_day_first
    try:
        svc._csv_decimal = lambda value, decimal_comma=False: old_decimal(value)
        svc._csv_slash_day_first = lambda cells, delimiter: (
            None if old_day_first(cells, delimiter) is None else False
        )
        IBKRImportService().import_ibkr_csv(db, EXCEL_ES.splitlines()[0] + "\n" + EXCEL_ES.splitlines()[1])
    finally:
        svc._csv_decimal, svc._csv_slash_day_first = old_decimal, old_day_first
    assert _rows(db)[0][:2] == (Decimal("32725"), date(2026, 5, 3))
    again = IBKRImportService().import_ibkr_csv(db, EXCEL_ES.splitlines()[0] + "\n" + EXCEL_ES.splitlines()[1])
    assert again["trades_imported"] == 0
    assert again["legacy_reimport_blocked"] == 1
    assert db.query(Transaction).count() == 1
    db.close()
