"""Alertas de precio: un umbral absurdo (1e308) se guardaba.

``price_above`` con 1e308 no puede dispararse nunca y ``price_below`` con 1e308
se cumple siempre. Las operaciones de cartera ya limitan el precio a lo que cabe
en su columna (``Numeric(20, 6)``); la alerta usa el mismo techo.
"""

import pytest
from pydantic import ValidationError

from app.api.routes.alerts import ManualAlertCreate


@pytest.mark.parametrize("value", [1e308, "1e308", 1e15, "100000000000000"])
@pytest.mark.parametrize(("alert_type", "operator"), [("price_above", ">"), ("price_below", "<")])
def test_precio_de_alerta_absurdo_se_rechaza(alert_type, operator, value):
    with pytest.raises(ValidationError, match="El precio de la alerta es demasiado alto"):
        ManualAlertCreate(ticker="AAPL", alert_type=alert_type, operator=operator, value=value)


@pytest.mark.parametrize("value", [0.0001, 185.5, "99999999999999.999999", 7_000_000])
def test_precios_reales_siguen_valiendo(value):
    rule = ManualAlertCreate(ticker="BRK.A", alert_type="price_above", operator=">=", value=value)
    assert rule.value == value


def test_cambio_porcentual_no_usa_el_techo_de_precio():
    rule = ManualAlertCreate(ticker="AAPL", alert_type="price_change", operator=">", value=1e15)
    assert rule.value == 1e15
