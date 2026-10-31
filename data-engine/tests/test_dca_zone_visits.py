"""Tests de zone_visits: duración de las visitas a la zona de compra (2X-4X).

Solo meses confirmados (sin look-ahead, como hit_rates); solo visitas
COMPLETADAS entran en la media; la racha abierta se declara y no cuenta.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from app.services.dca_signal_engine import NICO_V0_PARAMS, DailyBar, zone_visits

PARAMS = replace(
    NICO_V0_PARAMS, signal="drawdown", dd_thresholds=(0.15, 0.25, 0.40),
    min_months=3, high_lookback_months=36,
)


def _month_end_bars(closes: list[float], start: date = date(2018, 1, 1)) -> list[DailyBar]:
    bars = []
    y, m = start.year, start.month
    for c in closes:
        bars.append(DailyBar(day=date(y, m, 15), close=c))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return bars


def test_zone_visits_completed_average_and_open_streak() -> None:
    # 1X x5, 2X x3 (visita A), 1X x4, 4X x2 (visita B), 1X x3, 3X x2 (último mes
    # en formación: la visita C queda abierta con 1 mes confirmado y NO cuenta).
    closes = [100.0] * 5 + [80.0] * 3 + [120.0] * 4 + [70.0] * 2 + [130.0] * 3 + [97.5] * 2
    bars = _month_end_bars(closes)
    out = zone_visits(bars, params=PARAMS, today=bars[-1].day)
    assert out["available"] is True
    assert out["levels"] == [2, 3, 4]
    assert out["completed_visits"] == 2
    assert out["visits"] == [
        {"start": "2018-06", "end": "2018-08", "months": 3},
        {"start": "2019-01", "end": "2019-02", "months": 2},
    ]
    assert out["avg_months"] == 2.5
    assert out["max_months"] == 3
    assert out["open_visit_months"] == 1
    assert out["months_completed"] == len(closes) - 2 - 1


def test_zone_visits_run_at_the_end_is_open_not_completed() -> None:
    # La racha de 2X llega al último mes confirmado: abierta, no entra en la media.
    closes = [100.0] * 5 + [80.0] * 2
    bars = _month_end_bars(closes)
    out = zone_visits(bars, params=PARAMS, today=bars[-1].day)
    assert out["completed_visits"] == 0
    assert out["avg_months"] is None
    assert out["visits"] == []
    assert out["open_visit_months"] == 1


def test_zone_visits_none_when_never_in_zone() -> None:
    bars = _month_end_bars([100.0] * 8)
    out = zone_visits(bars, params=PARAMS, today=bars[-1].day)
    assert out["available"] is True
    assert out["completed_visits"] == 0
    assert out["avg_months"] is None
    assert out["open_visit_months"] is None


def test_zone_visits_unavailable_without_confirmed_months() -> None:
    bars = _month_end_bars([100.0] * 2)
    out = zone_visits(bars, params=PARAMS, today=bars[-1].day)
    assert out["available"] is False
    assert out["completed_visits"] == 0
    assert out["avg_months"] is None


def test_zone_visits_gap_inside_run_is_excluded_not_joined() -> None:
    # jun 2X, jul AUSENTE, ago 2X, sep/oct 1X: el hueco es desconocido; la
    # visita no demuestra 2 meses y se excluye (n visible), no se une.
    closes = [100.0] * 5 + [80.0] + [80.0] + [100.0, 100.0]
    bars = [
        b for i, b in enumerate(_month_end_bars(closes)) if i != 6  # sin julio
    ]
    out = zone_visits(bars, params=PARAMS, today=bars[-1].day)
    assert out["completed_visits"] == 0
    assert out["visits"] == []
    assert out["excluded_gap_visits"] == 1
    assert out["avg_months"] is None


def test_zone_visits_gap_at_closing_edge_is_excluded() -> None:
    # jun 2X, jul AUSENTE, ago 1X: la visita duro 1 o 2 meses (indeterminado).
    closes = [100.0] * 5 + [80.0] + [100.0, 100.0, 100.0]
    bars = [b for i, b in enumerate(_month_end_bars(closes)) if i != 6]
    out = zone_visits(bars, params=PARAMS, today=bars[-1].day)
    assert out["completed_visits"] == 0
    assert out["excluded_gap_visits"] == 1


def test_zone_visits_open_run_with_gap_declares_no_length() -> None:
    # Racha abierta con hueco dentro: no se declara largo y cuenta como excluida.
    closes = [100.0] * 5 + [80.0, 80.0, 80.0]
    bars = [b for i, b in enumerate(_month_end_bars(closes)) if i != 6]
    out = zone_visits(bars, params=PARAMS, today=bars[-1].day)
    assert out["completed_visits"] == 0
    assert out["open_visit_months"] is None
    assert out["excluded_gap_visits"] == 1
