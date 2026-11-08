"""Cambios de divisa, splits y CSV de actividad de IBKR contra SQLite real.

Cuarto lote de huecos de ibkr_import_service:

- Trade con assetCategory CASH (``EUR.USD``): NO es una compra de valores;
  va al libro de divisas (FxConversion) con patas disposed/acquired
  correctas en BUY y SELL, importes positivos, fecha EXACTA; nunca crea
  Transaction de acciones. Idempotente por trade id. Sin lado o sin
  importes legibles: se omite (nunca se inventa).
- Split FS con ratio legible («SPLIT 2 FOR 1»): se registra como accion
  corporativa PENDIENTE (applied=False, source ibkr_flex) y se avisa; no
  reescribe cantidades ni coste. SD (dividendo en acciones): solo aviso,
  sin registro de ratio.
- import_ibkr_csv (CSV interno de actividad): filas EUR (sin descarga BCE:
  el calentamiento FX solo actua con divisas != EUR), fecha EXACTA
  persistida, fila invalida omitida con numero de linea original,
  duplicados detectados al reimportar, cabecera invalida = error fatal,
  delimitador ``;`` con decimales de coma.

NO prueba (declarado): divisas != EUR en el CSV (calentamiento BCE, red),
reimportacion de CSV antiguo sin id (bloqueo legacy), splits aplicados al
libro (eso es CorporateActionService.apply_action), ni fidelidad contra
exports reales de IBKR (XML/CSV sinteticos).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models import CorporateAction
from app.models.entities import (
    Base,
    Company,
    FxConversion,
    Transaction,
)
from app.services.ibkr_import_service import IBKRImportError, IBKRImportService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session
    engine.dispose()


def _flex(*filas: str) -> str:
    cuerpo = "".join(filas)
    return (
        '<FlexQueryResponse queryName="q" type="AF">'
        f'<FlexStatements><FlexStatement accountId="U1" fromDate="2026-03-01" toDate="2026-03-31">'
        f"{cuerpo}</FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def test_cambio_divisa_buy_persiste_en_libro_fx(db):
    xml = _flex(
        '<Trades><Trade symbol="EUR.USD" assetCategory="CASH" buySell="BUY" '
        'quantity="1000" tradePrice="1.08" proceeds="-1080" '
        'tradeDate="2026-03-15" tradeID="FX1"/></Trades>'
    )
    resultado = IBKRImportService().import_flex_xml(db, xml, trades_only=True)
    assert resultado["fx_conversions_imported"] == 1
    assert resultado["non_stock_skipped"] == 1
    conversion = db.scalar(select(FxConversion))
    # BUY EUR.USD: compra EUR (adquirida) y gasta USD (dispuesta).
    assert conversion.acquired_currency == "EUR"
    assert conversion.acquired_amount == Decimal("1000")
    assert conversion.disposed_currency == "USD"
    assert conversion.disposed_amount == Decimal("1080")
    assert conversion.trade_date == date(2026, 3, 15)
    # Nunca es una compra de acciones: cero operaciones en el libro.
    assert db.scalar(select(func.count()).select_from(Transaction)) == 0


def test_cambio_divisa_sell_invierte_las_patas(db):
    xml = _flex(
        '<Trades><Trade symbol="EUR.USD" assetCategory="CASH" buySell="SELL" '
        'quantity="500" tradePrice="1.08" proceeds="540" '
        'tradeDate="2026-03-16" tradeID="FX2"/></Trades>'
    )
    resultado = IBKRImportService().import_flex_xml(db, xml, trades_only=True)
    assert resultado["fx_conversions_imported"] == 1
    conversion = db.scalar(select(FxConversion))
    assert conversion.disposed_currency == "EUR"
    assert conversion.disposed_amount == Decimal("500")
    assert conversion.acquired_currency == "USD"
    assert conversion.acquired_amount == Decimal("540")


def test_cambio_divisa_segundo_import_no_duplica(db):
    xml = _flex(
        '<Trades><Trade symbol="EUR.USD" assetCategory="CASH" buySell="BUY" '
        'quantity="1000" tradePrice="1.08" proceeds="-1080" '
        'tradeDate="2026-03-15" tradeID="FX1"/></Trades>'
    )
    servicio = IBKRImportService()
    servicio.import_flex_xml(db, xml, trades_only=True)
    segundo = servicio.import_flex_xml(db, xml, trades_only=True)
    assert segundo["fx_conversions_imported"] == 0
    assert segundo["fx_conversions_already_present"] == 1
    assert db.scalar(select(func.count()).select_from(FxConversion)) == 1


def test_cambio_divisa_sin_lado_se_omite(db):
    xml = _flex(
        '<Trades><Trade symbol="EUR.USD" assetCategory="CASH" '
        'quantity="1000" tradePrice="1.08" proceeds="-1080" '
        'tradeDate="2026-03-15" tradeID="FX3"/></Trades>'
    )
    resultado = IBKRImportService().import_flex_xml(db, xml, trades_only=True)
    assert resultado["fx_conversions_skipped"] == 1
    assert db.scalar(select(func.count()).select_from(FxConversion)) == 0


def test_split_fs_se_registra_como_pendiente(db):
    xml = _flex(
        '<Trades><Trade symbol="AAPL" assetCategory="STK" buySell="BUY" '
        'quantity="10" tradePrice="150.50" tradeDate="15/03/2026" '
        'currency="USD" tradeID="T1"/></Trades>'
        '<CorporateActions><CorporateAction symbol="AAPL" type="FS" '
        'description="AAPL (US0378331005) SPLIT 2 FOR 1" '
        'dateTime="20260316" transactionID="S1"/></CorporateActions>'
    )
    resultado = IBKRImportService().import_flex_xml(db, xml, trades_only=True)
    accion = db.scalar(select(CorporateAction))
    assert accion.action_type == "split"
    assert accion.ratio == Decimal("2")
    assert accion.effective_date == date(2026, 3, 16)
    assert accion.applied is False
    assert accion.source == "ibkr_flex"
    assert any("registrada como pendiente" in e for e in resultado["row_errors"])
    # El split NO reescribe el libro: la compra sigue como estaba.
    trade = db.scalar(select(Transaction))
    assert trade.quantity == Decimal("10")


def test_dividendo_en_acciones_sd_solo_avisa(db):
    xml = _flex(
        '<Trades><Trade symbol="AAPL" assetCategory="STK" buySell="BUY" '
        'quantity="10" tradePrice="150.50" tradeDate="15/03/2026" '
        'currency="USD" tradeID="T1"/></Trades>'
        '<CorporateActions><CorporateAction symbol="AAPL" type="SD" '
        'description="AAPL STOCK DIVIDEND" dateTime="20260316" '
        'transactionID="S2"/></CorporateActions>'
    )
    resultado = IBKRImportService().import_flex_xml(db, xml, trades_only=True)
    assert db.scalar(select(func.count()).select_from(CorporateAction)) == 0
    assert any("no se aplica al libro" in e for e in resultado["row_errors"])


_CSV = (
    "symbol,action,quantity,price,date,fees,currency\n"
    "SAN.MC,buy,10,4.12,15/03/2026,1.50,EUR\n"
)


def test_csv_persiste_operacion_con_fecha_exacta(db):
    resultado = IBKRImportService().import_ibkr_csv(db, _CSV)
    assert resultado["trades_imported"] == 1
    trade = db.scalar(select(Transaction))
    assert trade.trade_date == date(2026, 3, 15)
    assert trade.action == "buy"
    assert trade.quantity == Decimal("10")
    assert trade.price == Decimal("4.12")
    assert trade.fees == Decimal("1.50")
    assert trade.currency == "EUR"
    assert db.scalar(select(Company).where(Company.ticker == "SAN.MC")) is not None


def test_csv_fila_invalida_se_omite_con_numero_de_linea(db):
    csv_text = _CSV + "IBE.MC,buy,5,11.30,32/13/2026,0.50,EUR\n"
    resultado = IBKRImportService().import_ibkr_csv(db, csv_text)
    assert resultado["trades_imported"] == 1
    assert any(error.startswith("Fila 3") for error in resultado["row_errors"])


def test_csv_reimportar_no_duplica(db):
    servicio = IBKRImportService()
    primero = servicio.import_ibkr_csv(db, _CSV)
    segundo = servicio.import_ibkr_csv(db, _CSV)
    assert primero["trades_imported"] == 1
    assert segundo["trades_imported"] == 0
    assert segundo["duplicate_trades"] == 1
    assert db.scalar(select(func.count()).select_from(Transaction)) == 1


def test_csv_cabecera_invalida_es_error_fatal(db):
    with pytest.raises(IBKRImportError, match="cabecera"):
        IBKRImportService().import_ibkr_csv(db, "foo,bar\n1,2\n")


def test_csv_punto_y_coma_con_decimales_de_coma(db):
    csv_text = (
        "symbol;action;quantity;price;date;currency\n"
        "SAN.MC;buy;10;4,12;15/03/2026;EUR\n"
    )
    resultado = IBKRImportService().import_ibkr_csv(db, csv_text)
    assert resultado["trades_imported"] == 1
    trade = db.scalar(select(Transaction))
    assert trade.price == Decimal("4.12")
    assert trade.trade_date == date(2026, 3, 15)
