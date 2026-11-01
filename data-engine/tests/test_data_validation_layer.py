"""Pruebas exhaustivas para la capa de validación de datos financieros.

Fulfills: VAL-DATA-007
Expected Behavior:
- Ticker symbol validation (formato, caracteres permitidos, longitud)
- Price sanity checks (>0 para compras/mercado, rangos lógicos)
- Date validation (rechazo de fechas futuras para datos históricos)
- Quantity validation (>0 para compras/ventas)
- Mensajes de error claros, comprensibles y en español
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.local_date import local_today
from app.services.transaction_import_service import (
    TransactionImportService,
    normalize_action,
    parse_flexible_date,
)


def test_ticker_format_validation():
    """Valida que los tickers cumplan el estándar de nombres de mercado."""
    service = TransactionImportService()

    csv_data = (
        b"Fecha,Activo,Operacion,Cantidad,Precio\n"
        b"2026-01-10,SAN.MC,COMPRA,10,4.20\n"
        b"2026-01-10,INVALID$$TICKER!!,COMPRA,10,4.20\n"
        b"2026-01-10,,COMPRA,10,4.20\n"
    )

    prev = service.preview_import(csv_data, "tickers.csv")
    assert prev.valid_rows_count == 1
    assert prev.invalid_rows_count == 2
    ticker_errors = [e for e in prev.errors if e.field == "ticker"]
    assert len(ticker_errors) == 2
    assert any("obligatorio" in e.message.lower() for e in ticker_errors)
    assert any("no válido" in e.message.lower() for e in ticker_errors)


def test_date_not_future_validation():
    """Valida que no se acepten fechas en el futuro para datos históricos."""
    today = local_today()
    future = today + timedelta(days=2)

    with pytest.raises(ValueError, match="no puede ser futura"):
        parse_flexible_date(future.isoformat())

    # Pasado sí es válido
    past = today - timedelta(days=30)
    assert parse_flexible_date(past.isoformat()) == past


def test_price_sanity_checks():
    """Valida comprobaciones de cordura en precios (no negativos; una compra a 0 tampoco)."""
    service = TransactionImportService()

    csv_data = (
        b"Fecha,Activo,Operacion,Cantidad,Precio\n"
        b"2026-01-10,SAN.MC,COMPRA,10,-5.50\n"
        b"2026-01-10,SAN.MC,COMPRA,10,0.00\n"
        b"2026-01-10,SAN.MC,COMPRA,10,4.20\n"
    )

    prev = service.preview_import(csv_data, "precios.csv")
    price_errors = [e for e in prev.errors if e.field == "price"]
    assert len(price_errors) == 2
    assert "no puede ser negativo" in price_errors[0].message.lower()
    assert price_errors[1].message == "El precio de una compra debe ser mayor que cero"
    assert prev.valid_rows_count == 1


def test_quantity_strictly_positive_for_buys():
    """Valida que la cantidad sea estrictamente mayor que cero para operaciones de compra."""
    service = TransactionImportService()

    csv_data = (
        b"Fecha,Activo,Operacion,Cantidad,Precio\n"
        b"2026-01-10,SAN.MC,COMPRA,0,4.20\n"
        b"2026-01-10,SAN.MC,COMPRA,-15,4.20\n"
        b"2026-01-10,SAN.MC,COMPRA,100,4.20\n"
    )

    prev = service.preview_import(csv_data, "cantidades.csv")
    qty_errors = [e for e in prev.errors if e.field == "quantity"]
    assert len(qty_errors) == 2
    assert all("mayor que cero" in e.message.lower() for e in qty_errors)


def test_action_normalization_and_spanish_messages():
    """Valida que los tipos de operación se normalicen y rechacen valores espurios."""
    assert normalize_action("COMPRA") == "buy"
    assert normalize_action("VENTA") == "sell"
    assert normalize_action("DIVIDENDO") == "dividend"
    assert normalize_action("Buy") == "buy"

    with pytest.raises(ValueError, match="no reconocido"):
        normalize_action("ACCION_DESCONOCIDA_INVENTADA")
