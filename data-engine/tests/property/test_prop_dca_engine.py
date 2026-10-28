"""Invariantes del motor DCA (Formula Nico v1) buscadas con Hypothesis.

No se toca la formula: solo se comprueba que se comporta como dice su
contrato en series raras (planas, un punto, huecos, ceros, negativos, NaN).
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from hypothesis import assume, given
from hypothesis import strategies as st

from app.services.dca_signal_engine import (
    DEFAULT_PARAMS,
    LEVEL_LIGHT_TRIM,
    LEVEL_STRONG_TRIM,
    ZONES,
    DailyBar,
    evaluate_series,
)

ORDER = {LEVEL_STRONG_TRIM: -2, LEVEL_LIGHT_TRIM: -1, 1: 1, 2: 2, 3: 3, 4: 4}

weird_close = st.one_of(
    st.floats(min_value=0.01, max_value=1e6, allow_nan=False, allow_infinity=False),
    st.just(0.0),
    st.floats(max_value=-0.01, min_value=-1e3),
    st.just(float("nan")),
    st.just(float("inf")),
)


@st.composite
def monthly_bars(draw, min_months=1, max_months=60, weird=True, gaps=True):
    n = draw(st.integers(min_value=min_months, max_value=max_months))
    flat = draw(st.booleans())
    base = draw(st.floats(min_value=0.5, max_value=5000))
    bars = []
    month = date(2018, 1, 28)
    for _ in range(n):
        if gaps and draw(st.integers(0, 9)) == 0:
            month = (month.replace(day=1) + timedelta(days=32 * draw(st.integers(1, 6)))).replace(day=28)
        if flat:
            close = base
        elif weird:
            close = draw(weird_close)
        else:
            close = draw(st.floats(min_value=0.5, max_value=5000))
        low = draw(st.one_of(st.none(), st.floats(min_value=-10, max_value=1e6), st.just(float("nan"))))
        bars.append(DailyBar(day=month, close=close, low=low))
        month = (month.replace(day=1) + timedelta(days=32)).replace(day=28)
    return bars


def _finite_or_none(value):
    return value is None or isinstance(value, str) or (isinstance(value, (int, float)) and math.isfinite(value))


@given(monthly_bars())
def test_no_nan_or_inf_on_degenerate_series(bars):
    for verdict in evaluate_series(bars, today=date(2030, 1, 1)):
        assert verdict.level in ZONES
        assert math.isfinite(verdict.close) and verdict.close > 0
        for key, value in verdict.metrics.items():
            assert _finite_or_none(value), (key, value)
        for key, value in verdict.level_prices.items():
            assert value is None or (math.isfinite(value) and value > 0), (key, value)
        assert verdict.touched_level is None or verdict.touched_level in ZONES


@given(st.integers(min_value=1, max_value=80), st.floats(min_value=0.01, max_value=1e5))
def test_a_flat_series_never_reads_as_a_buy_discount(n, price):
    bars = [DailyBar(day=date(2015, 1, 28) + timedelta(days=31 * i), close=price) for i in range(n)]
    for verdict in evaluate_series(bars, today=date(2030, 1, 1)):
        # 0 % por debajo de la media: como mucho 2X (umbral 0 %), nunca 3X/4X.
        assert verdict.level <= 2


@given(monthly_bars(min_months=13, weird=False), st.floats(min_value=0.05, max_value=0.95))
def test_level_is_monotone_in_the_discount(bars, cut):
    """Con la historia (y por tanto la volatilidad) fija, bajar el ultimo
    cierre nunca baja el nivel (orden: recorte fuerte < ligero < 1X < ... < 4X)."""
    last = bars[-1]
    lower = [*bars[:-1], DailyBar(day=last.day, close=last.close * cut)]
    high = evaluate_series(bars, today=date(2030, 1, 1))
    low = evaluate_series(lower, today=date(2030, 1, 1))
    assume(high and low)
    assert ORDER[low[-1].level] >= ORDER[high[-1].level]


@given(monthly_bars(min_months=13, weird=False))
def test_level_prices_agree_with_the_level(bars):
    """El precio publicado para cada nivel es exactamente el cierre que lo activa."""
    v = evaluate_series(bars, today=date(2030, 1, 1))
    assume(v)
    last = v[-1]
    assume(last.level > 0)
    for n in (2, 3, 4):
        price = last.level_prices.get(f"{n}x")
        if price is None:
            continue
        if last.close < price * (1 - 1e-6):
            assert last.level >= n or (n == 4 and DEFAULT_PARAMS.cap4_before_months)
        if last.close > price * (1 + 1e-6):
            assert last.level < n


@given(monthly_bars(min_months=2, weird=False), st.integers(min_value=1, max_value=59))
def test_no_look_ahead(bars, cut):
    """El veredicto confirmado de un mes no cambia al llegar meses posteriores."""
    cut = min(cut, len(bars) - 1)
    full = {v.period: v for v in evaluate_series(bars, today=date(2030, 1, 1))}
    head = evaluate_series(bars[:cut], month_complete=True)
    for v in head:
        assert full[v.period].level == v.level
        assert full[v.period].level_prices == v.level_prices
