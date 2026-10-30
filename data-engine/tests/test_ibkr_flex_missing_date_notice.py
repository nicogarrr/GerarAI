"""Flex XML: una fila sin fecha se omite CON motivo, nunca en silencio.

Una operacion (Trade) o un movimiento de caja (CashTransaction) sin fecha pasaba
el validador (no habia valor que senalar) y el importador la descartaba con
rows_skipped=1 y row_errors vacio: el usuario veia «importado» y la operacion no
aparecia, sin ninguna pista. Lo mismo con un dividendo (CorporateAction) sin
fecha o con fecha ilegible, que el validador no revisa.
"""

from sqlalchemy import create_engine

from app.core.database import Base
from app.models import Transaction
from app.services.ibkr_import_service import IBKRImportService
from tests.test_ibkr_import import _tenant_session


def _xml(rows: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<FlexQueryResponse queryName="t"><FlexStatements><FlexStatement accountId="U1">'
        f"{rows}</FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def _import(rows: str) -> tuple[dict, list[Transaction]]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = _tenant_session(engine)
    result = IBKRImportService().import_flex_xml(db, _xml(rows))
    return result, db.query(Transaction).all()


def test_trade_sin_fecha_se_omite_con_motivo():
    result, txs = _import(
        '<Trade symbol="AAPL" tradeID="T9" buySell="BUY" quantity="10" tradePrice="150" '
        'ibCommission="1" currency="USD"/>'
    )
    assert txs == []
    assert result["rows_skipped"] == 1
    assert any("AAPL" in e and "T9" in e and "falta la fecha" in e for e in result["row_errors"])


def test_movimiento_de_caja_sin_fecha_se_omite_con_motivo():
    result, txs = _import('<CashTransaction type="Dividends" trxID="D7" amount="15.5" currency="USD" symbol="KO"/>')
    assert txs == []
    assert any("D7" in e and "falta la fecha" in e for e in result["row_errors"])


def test_dividendo_corporativo_con_fecha_ilegible_se_omite_con_motivo():
    result, txs = _import(
        '<CorporateAction type="DIV" transactionID="C3" symbol="KO" amount="4" currency="USD" dateTime="ayer"/>'
    )
    assert txs == []
    assert any("C3" in e and "'ayer'" in e for e in result["row_errors"])


def test_fila_valida_sigue_importandose_sin_avisos():
    result, txs = _import(
        '<Trade symbol="AAPL" tradeID="T1" buySell="BUY" quantity="10" tradePrice="150" '
        'ibCommission="1" tradeDate="2024-01-05" currency="USD"/>'
    )
    assert len(txs) == 1 and result["row_errors"] == []
