"""Importación de operaciones: solo divisas reales en la vista previa y en el commit.

La vista previa aceptaba cualquier celda de tres letras («NaN», «XYZ») y el
commit, que recibe las filas del cliente, no miraba la divisa: «EURO» o
«1e30» entraban en la cartera y esa posición quedaba sin tipo de cambio para
siempre. Mismo criterio que POST /transactions (lista ISO 4217 + subunidades).
"""

import pytest
from pydantic import ValidationError

from app.services.transaction_import_service import (
    ParsedTransaction,
    TransactionImportCommitRequest,
    normalize_currency_cell,
)


@pytest.mark.parametrize("cell", ["NaN", "XYZ", "abc", "QQQ"])
def test_preview_rejects_invented_codes(cell):
    with pytest.raises(ValueError, match="Divisa no reconocida"):
        normalize_currency_cell(cell)


@pytest.mark.parametrize(
    ("cell", "code"),
    [("eur", "EUR"), ("USD", "USD"), ("GBp", "GBp"), ("GBX", "GBX"), ("zac", "ZAC"), ("€", "EUR"), ("", "EUR"), ("CNH", "CNH")],
)
def test_preview_keeps_real_codes(cell, code):
    assert normalize_currency_cell(cell) == code


def _commit(currency: str) -> TransactionImportCommitRequest:
    return TransactionImportCommitRequest(transactions=[ParsedTransaction(
        row_number=2, ticker="AAPL", date="2025-03-03", action="buy",
        quantity=1, price=10, currency=currency,
    )])


@pytest.mark.parametrize("currency", ["EURO", "1e30", "NaN", "XYZ", "€"])
def test_commit_rejects_rows_with_no_real_currency(currency):
    with pytest.raises(ValidationError, match="divisa"):
        _commit(currency)


@pytest.mark.parametrize("currency", ["EUR", "usd", "GBp", "GBX"])
def test_commit_accepts_real_currencies(currency):
    assert _commit(currency).transactions[0].currency == currency
