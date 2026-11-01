"""Importación genérica de operaciones: la columna de divisa.

«GBp» (peniques, como lo escribe Yahoo para Londres) se pasaba a mayúsculas y
quedaba «GBP» (libras): 1.500 peniques por acción entraban como 1.500 libras,
cien veces el coste real. Y un símbolo («€», «$») entraba tal cual como divisa,
que ningún tipo de cambio sabe convertir, así que la posición se quedaba sin
valor en la divisa base. Ahora la unidad se conserva, los símbolos se leen como
su código ISO y un texto que no es una divisa se marca como error de la fila.
"""
from __future__ import annotations

from app.services.transaction_import_service import TransactionImportService

HEADER = "Fecha,Ticker,Tipo,Cantidad,Precio,Divisa\n"


def _preview(rows: str):
    return TransactionImportService().preview_import((HEADER + rows).encode(), "ops.csv")


def test_gbp_pence_keeps_its_unit():
    result = _preview("2025-03-10,SHEL.L,compra,10,2650.5,GBp\n2025-03-11,VOD.L,compra,10,7.2,GBP\n")
    assert result.errors == []
    assert [item.currency for item in result.preview_items] == ["GBp", "GBP"]


def test_currency_symbols_read_as_iso_codes():
    result = _preview("2025-03-10,SAN.MC,compra,10,4.5,€\n2025-03-10,AAPL,compra,1,180,$\n2025-03-10,VOD.L,compra,1,7.2,£\n")
    assert result.errors == []
    assert [item.currency for item in result.preview_items] == ["EUR", "USD", "GBP"]


def test_lowercase_iso_code_is_uppercased_and_empty_defaults_to_eur():
    result = _preview("2025-03-10,AAPL,compra,1,180,usd\n2025-03-10,SAN.MC,compra,1,4.5,\n")
    assert result.errors == []
    assert [item.currency for item in result.preview_items] == ["USD", "EUR"]


def test_text_that_is_not_a_currency_is_a_row_error():
    result = _preview("2025-03-10,AAPL,compra,1,180,Dólares americanos\n")
    assert result.preview_items == []
    assert [(e.row_number, e.field) for e in result.errors] == [(2, "currency")]
