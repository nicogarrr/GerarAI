"""Vista previa de importación: los mismos topes que el commit. Antes una
cantidad/precio/comisión que no cabe en la columna salía como fila válida (el
precio llegaba como «inf») y el commit rechazaba después el lote entero."""

import pytest

from app.services.transaction_import_service import (
    ParsedTransaction,
    TransactionImportCommitRequest,
    TransactionImportService,
)

H = "ticker,date,quantity,price,action,currency,fees\n"


def _preview(row: str):
    return TransactionImportService().preview_import((H + row + "\n").encode(), "x.csv")


def _fields(result) -> set[str]:
    return {error.field for error in result.errors}


def test_precio_enorme_es_error_de_fila_no_inf():
    result = _preview("AAPL,2026-01-05,1," + "9" * 400 + ",buy,USD,0")
    assert result.valid_rows_count == 0
    assert "price" in _fields(result)


def test_cantidad_enorme_es_error_de_fila():
    result = _preview("AAPL,2026-01-05,123456789012345678901234567890,10,buy,USD,0")
    assert result.valid_rows_count == 0
    assert "quantity" in _fields(result)


def test_comision_enorme_es_error_de_fila():
    result = _preview("AAPL,2026-01-05,1,10,buy,USD," + "9" * 400)
    assert result.valid_rows_count == 0
    assert "fees" in _fields(result)


def test_cantidad_que_se_guardaria_como_cero_es_error():
    result = _preview("AAPL,2026-01-05,0.0000001,10,buy,USD,0")
    assert result.valid_rows_count == 0
    assert "quantity" in _fields(result)


def test_limites_validos_siguen_entrando():
    result = _preview("AAPL,2026-01-05,0.000001,99999999999999,buy,USD,2")
    assert result.valid_rows_count == 1, result.errors


def test_commit_rechaza_cantidad_que_redondea_a_cero():
    tx = ParsedTransaction(row_number=2, ticker="AAPL", date="2026-01-05", action="buy",
                           quantity=1e-7, price=10, currency="USD")
    with pytest.raises(ValueError, match="demasiado pequeña"):
        TransactionImportCommitRequest(transactions=[tx])
