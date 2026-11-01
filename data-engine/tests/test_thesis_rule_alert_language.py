"""Aviso de criterio de invalidación de tesis en el idioma guardado del usuario.

Con inglés guardado en Ajustes, «salta un criterio de invalidación de la tesis
(v3): margen de seguridad < 10,00 %. Valor actual: 4,50 %.» salía en castellano.
"""

from types import SimpleNamespace

from app.services.thesis_invalidation_rules import (
    CHANGE_SINCE_THESIS_PCT,
    MARGIN_OF_SAFETY_PCT,
    PRICE,
    alert_message,
)

COMPANY = SimpleNamespace(ticker="ASTS")


def _rule(metric, operator, value, **target):
    return SimpleNamespace(target={"metric": metric, **target}, condition={"operator": operator, "value": value})


def test_thesis_rule_alert_in_english():
    rule = _rule(MARGIN_OF_SAFETY_PCT, "<", 10, thesis_version=3)
    assert alert_message(COMPANY, rule, 4.5, "en") == (
        "ASTS: a thesis invalidation criterion was triggered (v3): margin of safety < 10.00%. Current value: 4.50%."
    )
    price = _rule(PRICE, "<=", 1234.5, description="Cae por debajo del suelo")
    assert alert_message(COMPANY, price, 1200, "en") == (
        "ASTS: a thesis invalidation criterion was triggered: «Cae por debajo del suelo» (price ≤ 1,234.50). "
        "Current value: 1,200.00."
    )
    change = _rule(CHANGE_SINCE_THESIS_PCT, ">", 50)
    assert "change since the thesis > 50.00%" in alert_message(COMPANY, change, 60, "en")


def test_thesis_rule_alert_unchanged_in_spanish():
    rule = _rule(MARGIN_OF_SAFETY_PCT, "<", 10, thesis_version=3)
    assert alert_message(COMPANY, rule, 4.5) == (
        "ASTS: salta un criterio de invalidación de la tesis (v3): margen de seguridad < 10,00 %. "
        "Valor actual: 4,50 %."
    )
