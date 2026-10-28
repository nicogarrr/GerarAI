"""Rentabilidades de cartera: TWR y agregacion por pesos."""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from hypothesis import given
from hypothesis import strategies as st

from app.services.portfolio_intelligence_service import PortfolioIntelligenceService as S

ret = st.floats(min_value=-0.5, max_value=0.5)


@given(st.lists(ret, max_size=40), st.data())
def test_twr_is_invariant_to_a_zero_flow_flat_day(returns, data):
    i = data.draw(st.integers(min_value=0, max_value=len(returns)))
    padded = [*returns[:i], 0.0, *returns[i:]]
    assert math.isclose(S._compound(padded), S._compound(returns), rel_tol=1e-12, abs_tol=1e-12)


@given(st.lists(st.one_of(st.floats(min_value=0.01, max_value=1e5), st.just(0.0), st.none()), min_size=2, max_size=40))
def test_daily_returns_never_fabricate_a_minus_100_day(prices):
    series = [
        SimpleNamespace(date=date(2025, 1, 1) + timedelta(days=i), adj_close=None if p is None else Decimal(str(p)))
        for i, p in enumerate(prices)
    ]
    for value in S._returns(series).values():
        assert value > -1 and math.isfinite(value)


@given(
    st.dictionaries(
        st.integers(1, 6),
        st.dictionaries(st.integers(0, 20).map(lambda d: date(2025, 1, 1) + timedelta(days=d)), ret, max_size=20),
        max_size=6,
    ),
    st.dictionaries(st.integers(1, 6), st.one_of(st.just(0.0), st.floats(min_value=1e-6, max_value=1.0)), max_size=6),
)
def test_portfolio_return_is_a_convex_mix_of_its_holdings(returns, weights):
    out = S._portfolio_returns(returns, weights)
    for day, value in out.items():
        members = [series[day] for cid, series in returns.items() if day in series and weights.get(cid, 0) > 0]
        assert members
        assert min(members) - 1e-12 <= value <= max(members) + 1e-12


@given(st.lists(ret, max_size=60))
def test_max_drawdown_is_between_minus_one_and_zero(returns):
    series = {date(2025, 1, 1) + timedelta(days=i): r for i, r in enumerate(returns)}
    dd = S._drawdown(S.__new__(S), series)["max_drawdown"]
    if not returns:
        assert dd is None
    else:
        assert -1 <= dd <= 0
