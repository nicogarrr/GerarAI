"""Importacion Flex de IBKR contra SQLite real en memoria (trades_only e income).

Segundo lote de huecos de ibkr_import_service: el primero
(tests/test_ibkr_import_gaps.py) cubrio validacion y helpers de parseo sin
BD. Aqui se ejerce la escritura real del libro de operaciones:

- trades_only=True: compras/ventas de acciones con fecha EXACTA persistida
  (fechas con barra dd/mm y fechas ISO), comision en valor absoluto y
  emisor creado.
- Idempotencia por trade id: un segundo import del mismo extracto no
  duplica la operacion.
- dry_run=True: calcula el resultado y hace rollback; no queda nada en BD.
- Anulaciones (BUY (Ca.) con origTradeID): la original pasa a "cancelled"
  con su rastro y la anulacion queda como fila "cancel" propia.
- include_cash_income=True: dividendos y retenciones (CashTransaction) se
  persisten atribuidos al emisor; depositos/retiradas (cash_misc) se omiten.
- Fila sin fecha: se omite con aviso y NO impide importar la fila valida.
- _statement_is_older (guarda de frescura): statement_as_of directo,
  evidencia de operacion posterior y de fila cruda posterior, y el caso
  sin evidencia (se importa).

NO prueba (declarado): el camino de importacion completa (posiciones,
caja, snapshot, reconcile), que ademas encola trabajos en segundo plano;
la fidelidad contra un extracto real de IBKR (los XML son sinteticos); la
guarda de frescura solo se ejerce como metodo aislado con filas reales en
SQLite, no a traves del import de posiciones.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import (
    Base,
    Company,
    IbkrRawRow,
    Portfolio,
    Position,
    Transaction,
)
from app.services.ibkr_import_service import IBKRImportService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _flex(*filas: str) -> str:
    cuerpo = "".join(filas)
    return (
        '<FlexQueryResponse queryName="q" type="AF">'
        f'<FlexStatements><FlexStatement accountId="U1" fromDate="2026-03-01" toDate="2026-03-31">'
        f"{cuerpo}</FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def _servicio() -> IBKRImportService:
    return IBKRImportService()


def _transacciones(db) -> list[Transaction]:
    return list(db.scalars(select(Transaction).order_by(Transaction.id)).all())


def test_trades_only_persiste_trade_con_fecha_barra_exacta(db):
    xml = _flex(
        '<Trades><Trade symbol="AAPL" assetCategory="STK" buySell="BUY" '
        'quantity="10" tradePrice="150.50" tradeDate="15/03/2026" '
        'ibCommission="-1.25" currency="USD" tradeID="T1" listingExchange="NASDAQ"/></Trades>'
    )
    resultado = _servicio().import_flex_xml(db, xml, trades_only=True)
    assert resultado["status"] == "imported"
    assert resultado["trades_imported"] == 1
    operaciones = _transacciones(db)
    assert len(operaciones) == 1
    trade = operaciones[0]
    # La fecha con barra dd/mm se persiste con su VALOR EXACTO (15 de marzo,
    # no 3 de un mes inventado): antes solo se comprobaba que no daba error.
    assert trade.trade_date == date(2026, 3, 15)
    assert trade.action == "buy"
    assert trade.quantity == Decimal("10")
    assert trade.price == Decimal("150.50")
    assert trade.fees == Decimal("1.25")
    assert trade.currency == "USD"
    assert trade.external_id == "T1"
    assert db.scalar(select(Company).where(Company.ticker == "AAPL")) is not None


def test_trades_only_persiste_fecha_iso_exacta(db):
    xml = _flex(
        '<Trades><Trade symbol="MSFT" assetCategory="STK" buySell="SELL" '
        'quantity="4" tradePrice="410" tradeDate="2026-03-05" '
        'currency="USD" tradeID="T2"/></Trades>'
    )
    resultado = _servicio().import_flex_xml(db, xml, trades_only=True)
    assert resultado["trades_imported"] == 1
    trade = _transacciones(db)[0]
    assert trade.trade_date == date(2026, 3, 5)
    assert trade.action == "sell"


def test_segundo_import_del_mismo_extracto_no_duplica(db):
    xml = _flex(
        '<Trades><Trade symbol="AAPL" assetCategory="STK" buySell="BUY" '
        'quantity="10" tradePrice="150.50" tradeDate="2026-03-15" '
        'currency="USD" tradeID="T1"/></Trades>'
    )
    servicio = _servicio()
    primero = servicio.import_flex_xml(db, xml, trades_only=True)
    segundo = servicio.import_flex_xml(db, xml, trades_only=True)
    assert primero["trades_imported"] == 1
    assert segundo["trades_imported"] == 0
    assert segundo["trades_already_present"] == 1
    assert db.scalar(select(func.count()).select_from(Transaction)) == 1


def test_dry_run_calcula_sin_persistir(db):
    xml = _flex(
        '<Trades><Trade symbol="AAPL" assetCategory="STK" buySell="BUY" '
        'quantity="10" tradePrice="150.50" tradeDate="2026-03-15" '
        'currency="USD" tradeID="T1"/></Trades>'
    )
    resultado = _servicio().import_flex_xml(db, xml, trades_only=True, dry_run=True)
    assert resultado["status"] == "dry_run"
    assert resultado["trades_imported"] == 1
    assert db.scalar(select(func.count()).select_from(Transaction)) == 0
    assert db.scalar(select(func.count()).select_from(IbkrRawRow)) == 0


def test_anulacion_neutraliza_la_original_y_deja_rastro(db):
    xml = _flex(
        '<Trades>'
        '<Trade symbol="AAPL" assetCategory="STK" buySell="BUY" quantity="10" '
        'tradePrice="150.50" tradeDate="15/03/2026" currency="USD" tradeID="T1"/>'
        '<Trade symbol="AAPL" assetCategory="STK" buySell="BUY (Ca.)" quantity="10" '
        'tradePrice="150.50" tradeDate="16/03/2026" currency="USD" tradeID="T1C" '
        'origTradeID="T1"/>'
        "</Trades>"
    )
    resultado = _servicio().import_flex_xml(db, xml, trades_only=True)
    assert resultado["trades_cancelled"] == 1
    operaciones = {t.external_id: t for t in _transacciones(db)}
    assert operaciones["T1"].action == "cancelled"
    assert operaciones["T1"].raw_payload.get("cancelled_by") == "T1C"
    assert operaciones["T1C"].action == "cancel"
    assert operaciones["T1C"].raw_payload.get("cancels") == "T1"
    assert operaciones["T1C"].trade_date == date(2026, 3, 16)


def test_anulacion_sin_unica_original_se_omite_con_aviso(db):
    xml = _flex(
        '<Trades><Trade symbol="AAPL" assetCategory="STK" buySell="BUY (Ca.)" '
        'quantity="10" tradePrice="150.50" tradeDate="16/03/2026" currency="USD" '
        'tradeID="T9"/></Trades>'
    )
    resultado = _servicio().import_flex_xml(db, xml, trades_only=True)
    assert resultado["trades_cancelled"] == 0
    assert any("no se localizo una unica operacion" in e for e in resultado["row_errors"])
    assert _transacciones(db) == []


def test_dividendo_cash_transaction_atribuido_al_emisor(db):
    xml = _flex(
        '<Trades><Trade symbol="AAPL" assetCategory="STK" buySell="BUY" '
        'quantity="10" tradePrice="150.50" tradeDate="15/03/2026" '
        'currency="USD" tradeID="T1"/></Trades>'
        '<CashTransactions><CashTransaction symbol="AAPL" type="Dividends" '
        'amount="25.50" dateTime="2026-03-20" currency="USD" '
        'transactionID="C1"/></CashTransactions>'
    )
    resultado = _servicio().import_flex_xml(
        db, xml, trades_only=True, include_cash_income=True
    )
    assert resultado["dividends_imported"] == 1
    dividendo = next(t for t in _transacciones(db) if t.external_id == "C1")
    assert dividendo.action == "dividend"
    assert dividendo.trade_date == date(2026, 3, 20)
    assert dividendo.price == Decimal("25.50")
    emisor = db.scalar(select(Company).where(Company.ticker == "AAPL"))
    assert dividendo.company_id == emisor.id


def test_retencion_se_persiste_como_withholding(db):
    xml = _flex(
        '<CashTransactions><CashTransaction symbol="AAPL" '
        'type="Withholding Tax" amount="-3.83" dateTime="2026-03-20" '
        'currency="USD" transactionID="C2"/></CashTransactions>'
    )
    resultado = _servicio().import_flex_xml(
        db, xml, trades_only=True, include_cash_income=True
    )
    assert resultado["dividends_imported"] == 0
    retencion = _transacciones(db)[0]
    assert retencion.action == "withholding"
    assert retencion.price == Decimal("-3.83")


def test_deposito_se_omite_en_trades_only(db):
    xml = _flex(
        '<CashTransactions><CashTransaction type="Deposits &amp; Withdrawals" '
        'amount="1000" dateTime="2026-03-20" currency="EUR" '
        'transactionID="C3"/></CashTransactions>'
    )
    resultado = _servicio().import_flex_xml(
        db, xml, trades_only=True, include_cash_income=True
    )
    assert resultado["cash_misc_skipped"] == 1
    assert _transacciones(db) == []


def test_fila_sin_fecha_se_omite_y_la_valida_entra(db):
    xml = _flex(
        '<Trades>'
        '<Trade symbol="AAPL" assetCategory="STK" buySell="BUY" quantity="10" '
        'tradePrice="150.50" currency="USD" tradeID="SINFECHA"/>'
        '<Trade symbol="MSFT" assetCategory="STK" buySell="BUY" quantity="4" '
        'tradePrice="410" tradeDate="2026-03-05" currency="USD" tradeID="T2"/>'
        "</Trades>"
    )
    resultado = _servicio().import_flex_xml(db, xml, trades_only=True)
    assert resultado["trades_imported"] == 1
    assert resultado["rows_skipped"] == 1
    assert any("Trade" in e for e in resultado["row_errors"])
    assert [t.external_id for t in _transacciones(db)] == ["T2"]


def _cartera_y_emisor(db):
    portfolio = Portfolio(name="Main", base_currency="EUR", is_default=True)
    company = Company(
        ticker="AAPL", name="AAPL", exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add_all([portfolio, company])
    db.commit()
    return portfolio, company


def _posicion(db, portfolio, company, **campos) -> Position:
    posicion = Position(
        portfolio_id=portfolio.id, company_id=company.id,
        quantity=Decimal("10"), average_cost=Decimal("100"), currency="USD",
        **campos,
    )
    db.add(posicion)
    db.commit()
    return posicion


def test_guarda_frescura_statement_as_of_posterior_dice_antiguo(db):
    portfolio, company = _cartera_y_emisor(db)
    posicion = _posicion(db, portfolio, company, statement_as_of=date(2026, 4, 1))
    assert IBKRImportService._statement_is_older(db, posicion, company, date(2026, 3, 31)) is True
    assert IBKRImportService._statement_is_older(db, posicion, company, date(2026, 4, 1)) is False


def test_guarda_frescura_operacion_posterior_dice_antiguo(db):
    portfolio, company = _cartera_y_emisor(db)
    posicion = _posicion(db, portfolio, company, statement_as_of=None)
    db.add(Transaction(
        portfolio_id=portfolio.id, company_id=company.id,
        trade_date=date(2026, 4, 2), action="buy", quantity=Decimal("1"),
        price=Decimal("1"), fees=Decimal("0"), currency="USD", external_id="POST",
    ))
    db.commit()
    assert IBKRImportService._statement_is_older(db, posicion, company, date(2026, 3, 31)) is True


def test_guarda_frescura_fila_cruda_posterior_dice_antiguo(db):
    portfolio, company = _cartera_y_emisor(db)
    posicion = _posicion(db, portfolio, company, statement_as_of=None)
    db.add(IbkrRawRow(
        section="OpenPositions", path="OpenPositions/OpenPosition",
        row_hash="h1", symbol="AAPL", report_date=date(2026, 4, 2), payload={},
    ))
    db.commit()
    assert IBKRImportService._statement_is_older(db, posicion, company, date(2026, 3, 31)) is True


def test_guarda_frescura_sin_evidencia_importa(db):
    portfolio, company = _cartera_y_emisor(db)
    posicion = _posicion(db, portfolio, company, statement_as_of=None)
    # Sin fecha propia ni evidencia posterior no se puede probar que el
    # extracto sea mas antiguo: se importa (False).
    assert IBKRImportService._statement_is_older(db, posicion, company, date(2026, 3, 31)) is False
