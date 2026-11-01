"""La API de alertas acepta lo mismo que la web en alertas de precio.

La web (AlertsManager, QuickAlertPopover) deriva el operador del tipo —
«precio por encima» siempre «>», «por debajo» siempre «<»— y rechaza un precio
<= 0. La API, en cambio, guardaba ``price_above`` con «<» (una regla que se
llama «por encima de 300» pero avisa cuando el precio BAJA de 300) y umbrales 0
o negativos, que se cumplen siempre (price_above > 0) o nunca (price_below < 0).
"""

import pytest
from pydantic import ValidationError

from app.api.routes.alerts import ManualAlertCreate


@pytest.mark.parametrize(
    ("alert_type", "operator"),
    [
        ("price_above", "<"),
        ("price_above", "<="),
        ("price_above", "=="),
        ("price_below", ">"),
        ("price_below", ">="),
        ("price_below", "=="),
    ],
)
def test_price_alert_rejects_operator_against_its_direction(alert_type, operator):
    with pytest.raises(ValidationError, match="dirección"):
        ManualAlertCreate(ticker="AAPL", alert_type=alert_type, operator=operator, value=300)


@pytest.mark.parametrize("alert_type", ["price_above", "price_below"])
@pytest.mark.parametrize("value", [0, "0", -5, "-0.01"])
def test_price_alert_rejects_non_positive_price(alert_type, value):
    operator = ">" if alert_type == "price_above" else "<"
    with pytest.raises(ValidationError, match="mayor que 0"):
        ManualAlertCreate(ticker="AAPL", alert_type=alert_type, operator=operator, value=value)


@pytest.mark.parametrize(
    ("alert_type", "operator"),
    [("price_above", ">"), ("price_above", ">="), ("price_below", "<"), ("price_below", "<=")],
)
def test_price_alert_accepts_what_the_web_sends(alert_type, operator):
    payload = ManualAlertCreate(ticker="AAPL", alert_type=alert_type, operator=operator, value="300.5")
    assert payload.operator == operator


@pytest.mark.parametrize(("operator", "value"), [("<", -5), (">", 3), (">", 0)])
def test_price_change_keeps_both_directions_and_signed_values(operator, value):
    payload = ManualAlertCreate(ticker="AAPL", alert_type="price_change", operator=operator, value=value)
    assert payload.value == value
