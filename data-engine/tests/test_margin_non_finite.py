"""NaN/inf no se convierten en margen de seguridad ni en valor justo.

Hallado con Hypothesis (tests/property/test_prop_margin.py): con un valor
esperado NaN (0/0 de pandas en un motor) ``margin_of_safety`` devolvia NaN, y
NaN pasa ``value <= 0`` sin disparar el N/D: el margen salia NaN hacia la API,
el chat y el screener. ``float("inf")`` daba NaN igual ((inf - p)/inf), y un
valor justo "Infinity" leido de un payload JSON pasaba ``_positive``.
"""

import math

import pytest

from app.services import user_context
from app.services.fair_value_service import _positive
from app.valuation.engines import base

NAN = float("nan")
INF = float("inf")


@pytest.mark.parametrize("fn", [base.margin_of_safety, user_context.margin_of_safety])
@pytest.mark.parametrize(
    ("value", "price"),
    [(NAN, 100.0), (100.0, NAN), (INF, 100.0), (100.0, INF), (-INF, 100.0), (NAN, NAN)],
)
def test_non_finite_inputs_give_none_not_nan(fn, value, price):
    assert fn(value, price) is None


@pytest.mark.parametrize("fn", [base.margin_of_safety, user_context.margin_of_safety])
def test_finite_inputs_unchanged(fn):
    assert math.isclose(fn(130.0, 100.0), 30 / 130)
    assert fn(0.0, 100.0) is None
    assert fn(100.0, 0.0) is None


@pytest.mark.parametrize("raw", [INF, "inf", "Infinity", NAN, "nan", -1, 0])
def test_fair_value_candidate_rejects_non_finite(raw):
    assert _positive(raw) is None


def test_fair_value_candidate_keeps_positive_numbers():
    assert _positive("42.5") == 42.5
