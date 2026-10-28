"""Saldo medio del 4T del Modelo 720: sin observaciones futuras y monotono."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.services.tax_modelo720_service import Q4_MAX_GAP_DAYS, q4_average_detail

YEAR = 2025
Q_START = date(YEAR, 10, 1)
Q_END = date(YEAR, 12, 31)

balance = st.integers(min_value=-10_000, max_value=200_000).map(Decimal)


@st.composite
def snapshots(draw):
    day = Q_START - timedelta(days=draw(st.integers(min_value=-10, max_value=12)))
    points = []
    while day <= Q_END + timedelta(days=3):
        points.append((day, draw(balance)))
        day += timedelta(days=draw(st.integers(min_value=1, max_value=9)))
    return points


def reference(points):
    """Saldo diario = ultima captura en o antes del dia; None sin cobertura."""
    window = sorted((d, b) for d, b in dict(points).items() if Q_START - timedelta(days=Q4_MAX_GAP_DAYS) <= d <= Q_END)
    if not window or window[0][0] > Q_START:
        return None
    days = [d for d, _ in window]
    if (Q_END - days[-1]).days > Q4_MAX_GAP_DAYS:
        return None
    if any((b - a).days > Q4_MAX_GAP_DAYS for a, b in zip(days, days[1:])):
        return None
    total = Decimal("0")
    for offset in range((Q_END - Q_START).days + 1):
        day = Q_START + timedelta(days=offset)
        total += [b for d, b in window if d <= day][-1]
    return total / Decimal(92)


@given(snapshots())
def test_matches_a_daily_carry_forward_reference(points):
    detail = q4_average_detail(points, YEAR)
    expected = reference(points)
    if expected is None:
        assert detail is None
    else:
        assert detail is not None and detail["average"] == expected
        assert detail["observed_days"] + detail["carried_days"] == 92
        assert detail["estimate"] == (detail["observed_days"] < 92)


@given(snapshots())
def test_never_uses_an_observation_after_the_quarter_start_for_earlier_days(points):
    if all(d > Q_START for d, _ in points):
        assert q4_average_detail(points, YEAR) is None


@given(snapshots(), st.data())
def test_raising_one_balance_never_lowers_the_average(points, data):
    i = data.draw(st.integers(min_value=0, max_value=len(points) - 1))
    bump = data.draw(st.integers(min_value=1, max_value=50_000))
    raised = [(d, b + bump if j == i else b) for j, (d, b) in enumerate(points)]
    a, b = q4_average_detail(points, YEAR), q4_average_detail(raised, YEAR)
    assert (a is None) == (b is None)
    if a is not None:
        assert b["average"] >= a["average"]
