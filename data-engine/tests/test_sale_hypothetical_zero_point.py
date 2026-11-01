"""Chat IRPF («si vendo…»): «0.125» es 0,125 y no 125.

`parse_number` tomaba «0.125» como miles es-ES (125): un precio de céntimos
escrito con punto multiplicaba por 1000 el coste o el precio de venta de la
simulación. Un grupo de miles nunca empieza por 0 (mismo criterio que
`number_parsing` y los formularios).
"""

from __future__ import annotations

from decimal import Decimal

from app.services.sale_hypothetical import parse_number, parse_purchase_lots, parse_sale_price


def test_zero_integer_with_point_is_decimal() -> None:
    assert parse_number("0.125") == Decimal("0.125")
    assert parse_number("0.500") == Decimal("0.5")


def test_spanish_thousands_still_read_as_thousands() -> None:
    assert parse_number("1.500") == Decimal("1500")
    assert parse_number("10.000.000") == Decimal("10000000")
    assert parse_number("1.234,5") == Decimal("1234.5")


def test_purchase_lot_price_in_cents() -> None:
    lots = parse_purchase_lots("compré 1000 acciones a 0.125 € el 3 de marzo de 2024")
    assert [lot.price for lot in lots] == [Decimal("0.125")]


def test_sale_price_in_cents() -> None:
    parsed = parse_sale_price("¿cuánto pago si vendo a 0.150 €?")
    assert parsed is not None
    assert parsed[0] == Decimal("0.150")
