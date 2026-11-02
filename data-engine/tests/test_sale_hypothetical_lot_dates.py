"""Lotes del chat de IRPF con la fecha entre la cantidad y el precio.

«compré 5 acciones el 10 de marzo a 150 $» tomaba el DÍA (10) como cantidad;
con el año, o con «el 10/03/2024» / «en marzo de 2024», no leía ningún lote y
la simulación caía a la cartera real. «de Apple Inc» (dos palabras de nombre)
tampoco se leía.
"""

from datetime import date
from decimal import Decimal as D

import pytest

from app.services.sale_hypothetical import parse_purchase_lots


def _lots(text):
    return [(lot.quantity, lot.price, lot.currency, lot.trade_date) for lot in parse_purchase_lots(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("compré 5 acciones el 10 de marzo a 150 $", [(D("5"), D("150"), "USD", None)]),
        ("compré 5 acciones el 10 de marzo de 2024 a 150 $", [(D("5"), D("150"), "USD", date(2024, 3, 10))]),
        ("compré 5 acciones el 10/03/2024 a 150 €", [(D("5"), D("150"), "EUR", date(2024, 3, 10))]),
        ("compré 5 acciones en marzo de 2024 a 150 €", [(D("5"), D("150"), "EUR", date(2024, 3, 1))]),
        (
            "compré 5 acciones de Apple el 10 de marzo de 2024 a 150 $; si vendo 3 a 200 $",
            [(D("5"), D("150"), "USD", date(2024, 3, 10))],
        ),
        ("compré 10 acciones de Apple Inc a 150 $", [(D("10"), D("150"), "USD", None)]),
    ],
)
def test_lot_with_date_or_two_word_name_between_quantity_and_price(text, expected):
    assert _lots(text) == expected


def test_lots_with_date_after_price_unchanged():
    assert _lots("compré 10 acciones a 150 $ el 3 de marzo de 2024 y otras 5 a 120 $ el 1 de junio de 2024") == [
        (D("10"), D("150"), "USD", date(2024, 3, 3)),
        (D("5"), D("120"), "USD", date(2024, 6, 1)),
    ]
    assert _lots("el 10 de marzo de 2024 compré 5 acciones a 150 $") == [(D("5"), D("150"), "USD", date(2024, 3, 10))]
