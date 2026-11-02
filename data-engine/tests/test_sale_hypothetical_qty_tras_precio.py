"""Chat de IRPF: «vendo a 30 € 10 acciones» vende 10, no toda la posición.

Con el precio ANTES de la cantidad, la cantidad no se leía y la simulación
vendía todas las acciones (cuota calculada sobre otra venta). La cantidad debe
llevar «acciones/títulos/participaciones» y no ser un lote de compra («… que
compré: 10 a 20 € y 5 acciones a 25 €» sigue vendiendo todo).
"""

from decimal import Decimal as D

import pytest

from app.services.sale_hypothetical import _sale_quantity

HELD = D("40")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("si vendo a 30 € 10 acciones, ¿cuánto pago?", D("10")),
        ("¿y si vendiera hoy a 30 $ 12 títulos?", D("12")),
        ("si vendo a 25,5 € 7 participaciones", D("7")),
        ("si vendo 10 a 30 €", D("10")),
        ("si vendo a 30 €", HELD),
        ("si vendo a 30 € las acciones que compré: 10 a 20 € y 5 acciones a 25 €", HELD),
        ("si vendo a 30 € las que tengo, 40 acciones", D("40")),
    ],
)
def test_sale_quantity_after_the_price(text, expected):
    assert _sale_quantity(text, HELD) == expected
