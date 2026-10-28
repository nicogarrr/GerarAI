"""CSV de IBKR con punto y coma (Excel en español), hallado por la suite E2E.

Excel/LibreOffice con configuración regional es-ES exportan «CSV» con «;»
como separador, porque la coma es el separador decimal (12,50). El
importador solo leía comas: la cabecera ``symbol;action;...`` llegaba como
una sola columna y el fichero entero se rechazaba («La cabecera del CSV no
tiene las columnas obligatorias»), justo en el caso para el que existe el
soporte de decimales es-ES.
"""
from decimal import Decimal

from sqlalchemy import create_engine

from app.core.database import Base
from app.models import Transaction
from app.services.ibkr_import_service import IBKRImportService, validate_ibkr_csv
from tests.test_ibkr_import import _tenant_session

SEMICOLON = (
    "symbol;action;quantity;price;date;fees;currency\n"
    "QAZ1;buy;1,5;12,50;2026-01-05;0,35;EUR\n"
    "QAZ2;buy;10;1.234,56;2026-01-06;0;EUR\n"
    "QAZ3;buy;10;100.25;2026-01-07;0;USD\n"
)
COMMA = (
    "symbol,action,quantity,price,date,fees,currency\n"
    'QAZ1,buy,"1,5","12,50",2026-01-05,"0,35",EUR\n'
    'QAZ2,buy,10,"1.234,56",2026-01-06,0,EUR\n'
    "QAZ3,buy,10,100.25,2026-01-07,0,USD\n"
)


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return _tenant_session(engine)


def test_semicolon_csv_validates():
    assert validate_ibkr_csv(SEMICOLON) == []


def test_semicolon_csv_imports_with_es_decimals():
    db = _db()
    result = IBKRImportService().import_ibkr_csv(db, SEMICOLON)
    assert result["trades_imported"] == 3
    got = sorted((t.quantity, t.price, t.fees, t.currency) for t in db.query(Transaction).all())
    assert got == sorted([
        (Decimal("1.5"), Decimal("12.50"), Decimal("0.35"), "EUR"),
        (Decimal("10"), Decimal("1234.56"), Decimal("0"), "EUR"),
        (Decimal("10"), Decimal("100.25"), Decimal("0"), "USD"),
    ])
    db.close()


def test_same_trades_with_either_separator_are_the_same_trades():
    """Reimportar el mismo extracto con el otro separador no duplica nada."""
    db = _db()
    IBKRImportService().import_ibkr_csv(db, SEMICOLON)
    again = IBKRImportService().import_ibkr_csv(db, COMMA)
    assert again["trades_imported"] == 0
    assert db.query(Transaction).count() == 3
    db.close()


def test_comma_csv_with_semicolon_inside_a_quoted_cell_still_reads_as_comma():
    csv_text = (
        "symbol,action,quantity,price,date,fees,currency,description\n"
        'QAZ9,buy,2,10.5,2026-01-08,0,USD,"nota; con punto y coma"\n'
    )
    assert validate_ibkr_csv(csv_text) == []
    db = _db()
    assert IBKRImportService().import_ibkr_csv(db, csv_text)["trades_imported"] == 1
    db.close()
