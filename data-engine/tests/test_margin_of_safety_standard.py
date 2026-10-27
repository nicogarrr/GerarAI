"""Margen de seguridad estándar (V - P)/V (Graham, cap. 20; Klarman)."""

import pytest

from app.valuation.engines.base import (
    margin_of_safety,
    margin_of_safety_from_upside,
    upside_from_margin_of_safety,
)


def test_margin_of_safety_is_discount_over_value_hand_computed():
    # V = 130, P = 100: (130 - 100)/130 = 0,230769...; el potencial V/P - 1
    # seria 0,30 (lo que se publicaba antes con el nombre de margen).
    assert margin_of_safety(130.0, 100.0) == pytest.approx(30 / 130)
    # V = 80, P = 100: (80 - 100)/80 = -0,25 (cara).
    assert margin_of_safety(80.0, 100.0) == pytest.approx(-0.25)
    assert margin_of_safety(100.0, 100.0) == 0.0


@pytest.mark.parametrize(
    ("value", "price"),
    [(None, 100.0), (100.0, None), (100.0, 0.0), (100.0, -5.0), (0.0, 100.0), (-84.7, 100.0)],
)
def test_margin_of_safety_is_none_without_a_readable_ratio(value, price):
    """Sin precio positivo o con valor no positivo: N/D, nunca -249 %."""
    assert margin_of_safety(value, price) is None


@pytest.mark.parametrize("upside", [-0.5, -0.2, 0.0, 0.3, 1.0, 4.0])
def test_upside_and_margin_round_trip(upside):
    margin = margin_of_safety_from_upside(upside)
    assert upside_from_margin_of_safety(margin) == pytest.approx(upside)
    # El signo nunca cambia: atractivo/caro sigue del mismo lado.
    assert (margin > 0) == (upside > 0)


def test_rating_thresholds_are_the_old_upside_thresholds():
    assert margin_of_safety_from_upside(0.30) == pytest.approx(1 - 1 / 1.3)  # 0,2308
    assert margin_of_safety_from_upside(-0.20) == pytest.approx(-0.25)
