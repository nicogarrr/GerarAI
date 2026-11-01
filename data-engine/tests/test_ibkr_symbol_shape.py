"""IBKR (CSV y Flex XML): un símbolo imposible es error de fila, no un 500.

``Company.ticker`` es String(20). Un símbolo de 25 caracteres, uno con un NUL o
un salto de línea («MS\nFT», válido en un CSV entre comillas o como ``&#10;`` en
el XML) o uno sin letras ni cifras («.») se daba por bueno: se creaba una ficha
con ese ticker y, en Postgres, el INSERT reventaba (500) y se perdía el fichero
entero, también en la sincronización automática. Ahora se omite solo esa fila
y se dice cuál. Opciones, futuros y bonos (símbolos OCC largos) siguen yendo
por su aviso de «no se importa», sin error nuevo.
"""

import pytest
from sqlalchemy import create_engine, select

from app.models.entities import Base, Company, Transaction
from app.services.ibkr_import_service import IBKRImportService, validate_flex_xml, validate_ibkr_csv
from tests.test_ibkr_import import _tenant_session

HEADER = "Symbol,Buy/Sell,Quantity,TradePrice,TradeDate\n"
GOOD_CSV = "OKA,BUY,5,10,2024-03-15\n"
GOOD_XML = '<Trade symbol="OKA" tradeID="G1" quantity="5" tradePrice="10" tradeDate="2026-08-20" buySell="BUY" currency="USD"/>'


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _xml(*rows: str, section: str = "Trades") -> str:
    return (
        '<?xml version="1.0"?><FlexQueryResponse><FlexStatements><FlexStatement accountId="U1">'
        f"<{section}>" + "".join(rows) + f"</{section}></FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def _tickers(db) -> list[str]:
    return sorted(db.scalars(select(Company.ticker)).all())


BAD_CSV_SYMBOLS = ['"MS\nFT"', "A" * 25, ".", "\x00X", "--"]


@pytest.mark.parametrize("symbol", BAD_CSV_SYMBOLS)
def test_csv_simbolo_imposible_es_error_de_fila(engine, symbol):
    csv = HEADER + f"{symbol},BUY,10,150,2024-03-15\n" + GOOD_CSV
    errors = validate_ibkr_csv(csv)
    assert len(errors) == 1 and "símbolo" in errors[0] and errors[0].startswith("Fila 2 "), errors
    with _tenant_session(engine) as db:
        result = IBKRImportService().import_ibkr_csv(db, csv)
        assert _tickers(db) == ["OKA"]
    assert any("símbolo" in e for e in result["row_errors"])


BAD_XML_SYMBOLS = ["A" * 25, "MS&#10;FT", ".", "A&#9;B"]


@pytest.mark.parametrize("symbol", BAD_XML_SYMBOLS)
def test_flex_simbolo_imposible_es_error_de_fila(engine, symbol):
    bad = GOOD_XML.replace('symbol="OKA"', f'symbol="{symbol}"').replace('tradeID="G1"', 'tradeID="B1"')
    xml = _xml(bad, GOOD_XML)
    errors = validate_flex_xml(xml)
    assert len(errors) == 1 and "símbolo" in errors[0], errors
    with _tenant_session(engine) as db:
        result = IBKRImportService().import_flex_xml(db, xml)
        assert _tickers(db) == ["OKA"]
        assert len(db.scalars(select(Transaction)).all()) == 1
    assert any("símbolo" in e for e in result["row_errors"])


def test_flex_posicion_y_dividendo_con_simbolo_imposible_se_omiten(engine):
    long_symbol = "B" * 25
    position = (
        f'<OpenPosition symbol="{long_symbol}" position="10" markPrice="10" positionValue="100" '
        'costBasisPrice="9" currency="USD" reportDate="2026-08-20"/>'
    )
    dividend = (
        f'<CashTransaction type="Dividends" symbol="{long_symbol}" transactionID="C1" '
        'amount="5" dateTime="2026-08-20" currency="USD"/>'
    )
    xml = (
        '<?xml version="1.0"?><FlexQueryResponse><FlexStatements><FlexStatement accountId="U1">'
        f"<OpenPositions>{position}</OpenPositions><CashTransactions>{dividend}</CashTransactions>"
        "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )
    errors = validate_flex_xml(xml)
    assert len(errors) == 2 and all("símbolo" in e for e in errors), errors
    with _tenant_session(engine) as db:
        IBKRImportService().import_flex_xml(db, xml)
        assert _tickers(db) == []


def test_opciones_con_simbolo_occ_largo_no_dan_error_nuevo(engine):
    option = (
        '<Trade symbol="AAPL  240315C00150000" assetCategory="OPT" multiplier="100" tradeID="O1" '
        'quantity="1" tradePrice="5" tradeDate="2026-08-20" buySell="BUY" currency="USD"/>'
    )
    assert validate_flex_xml(_xml(option, GOOD_XML)) == []
    csv = "Symbol,Buy/Sell,Quantity,TradePrice,TradeDate,AssetClass\nAAPL  240315C00150000,BUY,1,5,2024-03-15,OPT\n"
    assert validate_ibkr_csv(csv) == []


@pytest.mark.parametrize("symbol", ["BRK B", "BRK.B", "0700.HK", "RDS-A", "7203"])
def test_simbolos_reales_siguen_entrando(engine, symbol):
    assert validate_ibkr_csv(HEADER + f"{symbol},BUY,10,150,2024-03-15\n") == []


@pytest.mark.parametrize("lead", ["\n", "  \r\n", "\ufeff\n "])
def test_flex_con_linea_en_blanco_antes_de_la_declaracion_se_lee(engine, lead):
    # Copiar el XML desde el navegador deja a veces una línea en blanco delante
    # de «<?xml …?>»: antes salía «XML or text declaration not at start of entity».
    xml = lead + _xml(GOOD_XML)
    assert validate_flex_xml(xml) == []
    with _tenant_session(engine) as db:
        result = IBKRImportService().import_flex_xml(db, xml)
    assert result["trades_imported"] == 1
