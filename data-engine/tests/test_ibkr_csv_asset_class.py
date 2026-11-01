"""Un CSV de Flex Query de IBKR con opciones, bonos o divisas no debe meterlas como acciones.

El CSV que exporta una Flex Query de operaciones trae la columna «AssetClass»
(STK, OPT, FUT, BOND, CASH...) y «Multiplier». El importador del CSV no las
miraba: 1 call de AAPL comprada a 5 $ (multiplicador 100) entraba como 1
acción a 5 $ de coste en vez de 500 $, y un cambio EUR.USD como una «empresa»
EUR.USD. Es el mismo fallo que #3877 arregló en el Flex XML.
"""

from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService

FLEX_CSV = (
    "CurrencyPrimary,AssetClass,Symbol,Multiplier,TradeDate,Quantity,TradePrice,IBCommission,Buy/Sell,TradeID\n"
    "USD,STK,AAPL,1,20260105,10,180.50,-1.0,BUY,2001\n"
    "USD,OPT,AAPL  261218C00200000,100,20260106,1,5.00,-0.65,BUY,2002\n"
    "USD,BOND,US912828XX12,1,20260107,1000,99.5,-1.0,BUY,2003\n"
    "USD,CASH,EUR.USD,1,20260108,1000,1.08,-2.0,BUY,2004\n"
    "USD,FUT,ESZ6,50,20260109,1,5000,-2.0,BUY,2005\n"
)


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="csv-asset-class-test", name="csv asset class")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def test_csv_flex_solo_importa_acciones():
    db = _session()
    result = IBKRImportService().import_ibkr_csv(db, FLEX_CSV)

    rows = db.scalars(select(Transaction)).all()
    assert [(row.external_id, row.quantity, row.price) for row in rows] == [
        ("2001", Decimal("10"), Decimal("180.50"))
    ]
    assert result["trades_imported"] == 1
    assert result["rows_skipped"] == 4
    tickers = set(db.scalars(select(Company.ticker)).all())
    assert tickers == {"AAPL"}
    errors = " ".join(result["row_errors"])
    for line in ("Fila 3", "Fila 4", "Fila 5", "Fila 6"):
        assert line in errors
    assert "OPT" in errors and "BOND" in errors and "FUT" in errors


def test_csv_multiplicador_distinto_de_uno_sin_asset_class_se_omite():
    csv_text = (
        "Symbol,Multiplier,TradeDate,Quantity,TradePrice,Buy/Sell,TradeID\n"
        "MSFT,1,20260105,2,400,BUY,3001\n"
        "MSFT  261218C00500000,100,20260106,1,7.5,BUY,3002\n"
    )
    db = _session()
    result = IBKRImportService().import_ibkr_csv(db, csv_text)
    assert [row.external_id for row in db.scalars(select(Transaction)).all()] == ["3001"]
    assert result["rows_skipped"] == 1


def test_csv_sin_columnas_de_tipo_sigue_igual():
    csv_text = "symbol,action,quantity,price,date\nKO,buy,3,60,2026-01-05\n"
    db = _session()
    result = IBKRImportService().import_ibkr_csv(db, csv_text)
    assert result["trades_imported"] == 1 and result["rows_skipped"] == 0


def test_csv_flex_con_ordenes_y_resumen_no_duplica():
    csv_text = (
        "LevelOfDetail,Symbol,TradeDate,Quantity,TradePrice,Buy/Sell,TradeID,IBOrderID\n"
        "ORDER,KO,20260105,10,60,BUY,,9001\n"
        "EXECUTION,KO,20260105,4,60,BUY,4001,9001\n"
        "EXECUTION,KO,20260105,6,60,BUY,4002,9001\n"
        "SYMBOL_SUMMARY,KO,20260105,10,60,BUY,,\n"
    )
    db = _session()
    result = IBKRImportService().import_ibkr_csv(db, csv_text)
    rows = db.scalars(select(Transaction)).all()
    assert sorted(row.external_id for row in rows) == ["4001", "4002"]
    assert sum(row.quantity for row in rows) == Decimal("10")
    assert result["rows_skipped"] == 2
