"""Margen de seguridad y valor justo: signo coherente, None antes que 0 o NaN."""

from __future__ import annotations

import math
from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from app.services import user_context
from app.services.fair_value_service import Candidate, _positive, choose
from app.valuation.engines import base

# Magnitudes realistas (1e-6..1e9) mas los casos degenerados; con 1e-144
# frente a 1e165 el cociente desborda a -inf por aritmetica float, no por bug.
any_float = st.one_of(
    st.none(),
    st.sampled_from([0.0, -0.0, float("nan"), float("inf"), float("-inf")]),
    st.floats(min_value=1e-6, max_value=1e9),
    st.floats(min_value=-1e9, max_value=-1e-6),
)
positive = st.floats(min_value=1e-6, max_value=1e9)


def _check(margin_fn, value, price):
    m = margin_fn(value, price)
    if m is None:
        return
    assert math.isfinite(m), (value, price, m)
    assert m <= 1  # = 1 solo por redondeo float con V >> P
    # signo: valor > precio <=> margen positivo
    if value > price:
        assert m > 0
    elif value < price:
        assert m < 0
    else:
        assert m == 0


@given(any_float, any_float)
def test_engine_margin_is_finite_and_signed(value, price):
    _check(base.margin_of_safety, value, price)


@given(any_float, any_float)
def test_context_margin_is_finite_and_signed(value, price):
    _check(user_context.margin_of_safety, value, price)


@given(positive, positive)
def test_both_margin_implementations_agree(value, price):
    assert base.margin_of_safety(value, price) == user_context.margin_of_safety(value, price)


@given(st.floats(min_value=-0.99, max_value=0.99))
def test_margin_upside_round_trip(m):
    up = base.upside_from_margin_of_safety(m)
    assert math.isclose(base.margin_of_safety_from_upside(up), m, abs_tol=1e-9)


@given(st.one_of(st.none(), st.floats(), st.text(max_size=5), st.integers()))
def test_positive_never_lets_a_non_finite_value_through(raw):
    value = _positive(raw)
    assert value is None or (math.isfinite(value) and value > 0)


money = st.floats(min_value=0.01, max_value=1e9)  # choose() redondea a 4 decimales


@given(
    st.one_of(st.none(), st.builds(Candidate, value=money, as_of=st.one_of(st.none(), st.dates()), thesis_version=st.integers(1, 9))),
    st.one_of(st.none(), st.builds(Candidate, value=money, as_of=st.one_of(st.none(), st.dates()), publishable=st.booleans())),
)
def test_choose_never_invents_a_value(thesis, engine):
    today = date(2026, 10, 27)
    reading = choose(thesis, engine, today=today)
    fresh_orientative = (
        engine is not None
        and not engine.publishable
        and engine.as_of is not None
        and (today - engine.as_of).days <= 180
    )
    if thesis is None and engine is None:
        assert reading["value"] is None and reading["publishable"] is False
    elif thesis is not None or (engine is not None and engine.publishable) or fresh_orientative:
        assert reading["value"] is not None and reading["value"] > 0
    else:
        # Unico caso sin cifra habiendo motor: borrador orientativo caducado o
        # sin fecha (caduca como una tesis; nunca se sirve un numero viejo).
        assert reading["value"] is None and reading["publishable"] is False
        assert reading["reason"]
    if reading["source"] == "motor_orientativo":
        assert reading["publishable"] is False
