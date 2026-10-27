"""Un CSV exportado desde una Flex Query de IBKR debe importarse con su divisa.

La Flex Query de operaciones de IBKR exporta la cabecera con los nombres de
campo de IBKR: «Buy/Sell» para el sentido y «CurrencyPrimary» para la divisa.
Antes la cabecera se comparaba literal: «buy/sell» no casaba con el alias
«buysell» (400 por columnas obligatorias) y, aunque se renombrase, la divisa
no se reconocia y una compra de CGEO.L en GBP entraba como USD.
"""

from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService, validate_ibkr_csv

FLEX_CSV = """Symbol,Buy/Sell,Quantity,TradePrice,TradeDate,IBCommission,CurrencyPrimary,TradeID
CGEO.L,BUY,100,15.20,20240105,-3.0,GBP,1001
CGEO.L,SELL,-40,16.10,20240610,-2.5,GBP,1002
"""


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="csv-flex-test", name="csv flex")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def test_cabecera_flex_de_ibkr_es_valida():
    assert validate_ibkr_csv(FLEX_CSV) == []


def test_flex_csv_conserva_sentido_divisa_y_comision():
    db = _session()
    result = IBKRImportService().import_ibkr_csv(db, FLEX_CSV)
    assert result["rows_skipped"] == 0, result["row_errors"]
    assert result["trades_imported"] == 2

    rows = db.scalars(select(Transaction).order_by(Transaction.trade_date)).all()
    assert [(row.action, row.quantity, row.currency) for row in rows] == [
        ("buy", Decimal("100"), "GBP"),
        ("sell", Decimal("40"), "GBP"),
    ]
    assert [row.fees for row in rows] == [Decimal("3.0"), Decimal("2.5")]
    assert [row.external_id for row in rows] == ["1001", "1002"]


def test_cabecera_con_bom_de_excel_es_valida():
    assert validate_ibkr_csv("\ufeffsymbol,action,quantity,price,date\nCB,buy,2,250,2024-02-01\n") == []
