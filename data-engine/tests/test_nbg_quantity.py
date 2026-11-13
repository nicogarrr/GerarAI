"""Una cantidad base invalida no se sustituye por una unidad."""
import json
from decimal import Decimal

import pytest

from app.services.connectors.official_fx import parse_nbg


@pytest.mark.parametrize("quantity", [0, 0.0, False, None, "", -1, "0", "NaN", "Infinity"])
def test_nbg_rechaza_cantidad_invalida(quantity):
    payload = [{"date": "2026-11-13", "currencies": [
        {"code": "USD", "rate": 2.7, "quantity": quantity},
    ]}]
    with pytest.raises(ValueError, match="tipo o fecha"):
        parse_nbg(json.dumps(payload))


def test_nbg_no_inventa_cantidad_ausente():
    with pytest.raises(ValueError):
        parse_nbg(json.dumps([{"date": "2026-11-13", "currencies": [{"code": "USD", "rate": 2.7}]}]))


@pytest.mark.parametrize("quantity,expected", [(1, "2.7"), (100, "0.027")])
def test_nbg_conserva_divisor_valido(quantity, expected):
    rows = parse_nbg(json.dumps([{"date": "2026-11-13", "currencies": [
        {"code": "USD", "rate": 2.7, "quantity": quantity},
    ]}]))
    assert rows[0].units == Decimal(expected)
