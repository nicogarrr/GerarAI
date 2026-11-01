"""Flex XML de IBKR: un importe que no cabe o una comisión rota es error de fila.

Lo mismo que #4044 arregló en el CSV: ``validate_flex_xml`` solo miraba que
cantidad y precio fueran números. Un precio o una cantidad de 15 cifras se
importaban (en Postgres el INSERT en Numeric(20, 6) revienta: 500 y se pierde
el fichero entero, también en la sincronización automática), y una comisión
«-1e19» hacía que ``_decimal`` lanzara y se rechazara el fichero completo en
vez de solo esa operación. Mismos topes que POST /transactions (#2606).
"""

import pytest
from sqlalchemy import create_engine, select

from app.models.entities import Base, CashBalance, Position, Transaction
from app.services.ibkr_import_service import (
    IBKRImportService,
    validate_flex_xml,
    validate_ibkr_csv,
)
from tests.test_ibkr_import import _tenant_session

GOOD = '<Trade symbol="OKA" tradeID="G1" quantity="5" tradePrice="10" tradeDate="2026-08-20" buySell="BUY" currency="USD"/>'


def _xml(*rows: str, section: str = "Trades") -> str:
    return (
        '<?xml version="1.0"?><FlexQueryResponse><FlexStatements><FlexStatement accountId="U1">'
        f"<{section}>" + "".join(rows) + f"</{section}></FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def _trade(**attrs: str) -> str:
    base = {
        "symbol": "ZXA", "tradeID": "T1", "quantity": "5", "tradePrice": "10",
        "tradeDate": "2026-08-20", "buySell": "BUY", "currency": "USD",
    }
    base.update(attrs)
    return "<Trade " + " ".join(f'{k}="{v}"' for k, v in base.items()) + "/>"


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.mark.parametrize(
    ("attrs", "word"),
    [
        ({"tradePrice": "999999999999999"}, "precio"),
        ({"quantity": "999999999999999"}, "cantidad"),
        ({"ibCommission": "-1e19"}, "comisión"),
        ({"ibCommission": "-10000000000000000000"}, "comisión"),
        ({"ibCommission": "abc"}, "comisión"),
    ],
)
def test_operacion_fuera_de_rango_es_error_de_fila(engine, attrs, word):
    xml = _xml(_trade(**attrs), GOOD)
    errors = validate_flex_xml(xml)
    assert len(errors) == 1, errors
    assert word in errors[0] and "ZXA" in errors[0]
    with _tenant_session(engine) as db:
        result = IBKRImportService().import_flex_xml(db, xml)
        tickers = [t.raw_payload.get("symbol") for t in db.scalars(select(Transaction)).all()]
    assert result["trades_imported"] == 1
    assert tickers == ["OKA"]
    assert any(word in e for e in result["row_errors"])


def test_comision_normal_sigue_entrando(engine):
    with _tenant_session(engine) as db:
        result = IBKRImportService().import_flex_xml(db, _xml(_trade(ibCommission="-1.25")))
        fees = [t.fees for t in db.scalars(select(Transaction)).all()]
    assert result["trades_imported"] == 1 and result["row_errors"] == []
    assert [float(f) for f in fees] == [1.25]


def test_dividendo_que_no_cabe_se_omite(engine):
    big = (
        '<CashTransaction type="Dividends" symbol="ZXA" transactionID="C1" '
        'amount="999999999999999" dateTime="2026-08-20" currency="USD"/>'
    )
    xml = _xml(big, section="CashTransactions")
    errors = validate_flex_xml(xml)
    assert len(errors) == 1 and "demasiado grande" in errors[0], errors
    with _tenant_session(engine) as db:
        result = IBKRImportService().import_flex_xml(db, xml)
        rows = db.scalars(select(Transaction)).all()
    assert rows == []
    assert any("demasiado grande" in e for e in result["row_errors"])


def test_posicion_y_saldo_que_no_caben_se_omiten(engine):
    position = (
        '<OpenPosition symbol="ZXP" position="10" markPrice="999999999999999" '
        'positionValue="100" costBasisPrice="9" currency="USD" reportDate="2026-08-20"/>'
    )
    cash = '<CashReportCurrency currency="USD" endingCash="99999999999999999999" reportDate="2026-08-20"/>'
    xml = (
        '<?xml version="1.0"?><FlexQueryResponse><FlexStatements><FlexStatement accountId="U1">'
        f"<OpenPositions>{position}</OpenPositions><CashReport>{cash}</CashReport>"
        "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )
    errors = validate_flex_xml(xml)
    assert len(errors) == 2 and all("demasiado grande" in e for e in errors), errors
    with _tenant_session(engine) as db:
        IBKRImportService().import_flex_xml(db, xml)
        assert db.scalars(select(Position)).all() == []
        assert db.scalars(select(CashBalance)).all() == []


def test_notacion_cientifica_se_explica_en_flex_y_csv():
    flex = validate_flex_xml(_xml(_trade(quantity="1e23")))
    assert len(flex) == 1 and "notación científica" in flex[0], flex
    csv = validate_ibkr_csv(
        "Symbol,Buy/Sell,Quantity,TradePrice,TradeDate\nAAPL,BUY,10,1E+23,2024-03-15\n"
    )
    assert len(csv) == 1 and "notación científica" in csv[0], csv
    assert "no es un número" not in csv[0]
