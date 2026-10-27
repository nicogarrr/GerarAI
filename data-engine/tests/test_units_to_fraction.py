"""Helper único de unidades (auditoría: ``wacc_rate_normalization``)."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.units import to_fraction
from app.services.metric_calculation_service import MetricCalculationService


@pytest.mark.parametrize(
    ("value", "unit", "expected", "method"),
    [
        # El caso de la auditoría: 0,9 % en puntos con unidad declarada.
        ("0.9", "percent", Decimal("0.009"), "explicit_percent"),
        ("4.25", "%", Decimal("0.0425"), "explicit_percent"),
        ("0.0425", "decimal", Decimal("0.0425"), "explicit_fraction"),
        # Una fracción declarada > 1 NO se divide (ROE real del 150 %).
        ("1.5", "ratio", Decimal("1.5"), "explicit_fraction"),
        ("425", "bps", Decimal("0.0425"), "explicit_bps"),
        # Sin unidad útil: heurística histórica, marcada como tal.
        ("4.25", "USD", Decimal("0.0425"), "heuristic_percent"),
        ("0.9", None, Decimal("0.9"), "heuristic_fraction"),
    ],
)
def test_to_fraction_lee_la_unidad(value, unit, expected, method):
    assert to_fraction(Decimal(value), unit) == (expected, method)


def test_propiedad_percent_y_fraction_coinciden():
    """Propiedad: x % declarado == x/100 declarado como fracción, para todo x."""
    import random

    rng = random.Random(20261027)
    for _ in range(200):
        x = Decimal(str(round(rng.uniform(-50, 150), 4)))
        assert to_fraction(x, "percent")[0] == to_fraction(x / 100, "decimal")[0]


def test_tasa_en_puntos_menor_que_uno_ya_no_se_lee_como_90():
    """En main un tipo impositivo de 0,9 % con unidad 'percent' salía 0,9 (90 %)."""
    service = MetricCalculationService()
    rate, normalized = service._normalize_rate(Decimal("0.9"), unit="percent")
    assert rate == Decimal("0.009")
    assert normalized is True
    rate, normalized = service._normalize_rate(Decimal("4.25"))
    assert rate == Decimal("0.0425")
    assert normalized is True
    fact = SimpleNamespace(value=Decimal("21"), unit="percent")
    assert service._normalize_rate(fact.value, unit=fact.unit)[0] == Decimal("0.21")
