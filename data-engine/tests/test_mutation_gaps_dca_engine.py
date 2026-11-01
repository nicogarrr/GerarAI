"""DCA engine asserts that mutation testing (mutmut) showed were missing.

Mutants in these branches survived the existing suite: the level prices shown
to the user, the intra-month "touched" level, the RSI behind the strong trim
and the trailing volatility could all change silently. See
docs/testing/mutation.md.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import replace
from datetime import date

import pytest

from app.services.dca_signal_engine import (
    DEFAULT_PARAMS,
    LEVEL_LIGHT_TRIM,
    LEVEL_STRONG_TRIM,
    DailyBar,
    _rsi_series,
    _trailing_vol,
    current_verdict,
    evaluate_series,
)


def _bars(closes: list[float], lows: list[float | None] | None = None) -> list[DailyBar]:
    bars = []
    y, m = 2015, 1
    for idx, c in enumerate(closes):
        low = lows[idx] if lows else None
        bars.append(DailyBar(day=date(y, m, 15), close=c, low=low))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return bars


def _wavy(n: int) -> list[float]:
    # Deterministic series with real volatility (about 30-40 % a year).
    return [100.0 * (1.0 + 0.12 * math.sin(k / 2.0)) * (1.0 + 0.003 * k) for k in range(n)]


def _last(closes, params=DEFAULT_PARAMS, lows=None):
    return evaluate_series(_bars(closes, lows), params=params, month_complete=True)[-1]


# --- level prices: closing exactly at the published price gives that level ---


@pytest.mark.parametrize(
    "params",
    [
        DEFAULT_PARAMS,
        replace(DEFAULT_PARAMS, signal="drawdown"),
        replace(DEFAULT_PARAMS, vol_beta=0.0),
    ],
    ids=["sma_gap_vol_adjusted", "drawdown", "sma_gap_no_vol"],
)
@pytest.mark.parametrize("n", [2, 3, 4])
def test_level_price_round_trip(params, n):
    history = _wavy(60)
    probe = _last([*history, history[-1]], params)
    price = probe.level_prices[f"{n}x"]
    assert price is not None and price > 0
    # Published prices are rounded to 6 decimals; probe 1e-6 either side.
    at = _last([*history, price * (1 - 1e-6)], params)
    above = _last([*history, price * (1 + 1e-6)], params)
    assert at.level >= n
    assert above.level < n or above.level > 4  # strictly less buying (or a trim)
    # The prices of the same month do not depend on the close itself.
    assert at.level_prices == probe.level_prices


def test_level_prices_are_ordered():
    v = _last([*_wavy(60), 90.0])
    assert v.level_prices["2x"] > v.level_prices["3x"] > v.level_prices["4x"] > 0


def test_drawdown_level_prices_are_fractions_of_previous_high():
    params = replace(DEFAULT_PARAMS, signal="drawdown", min_months=3, cap4_before_months=None)
    v = _last([100.0, 120.0, 110.0, 105.0], params)
    assert v.metrics["signal"] == "drawdown"
    assert v.level_prices == {
        "2x": pytest.approx(102.0),
        "3x": pytest.approx(90.0),
        "4x": pytest.approx(72.0),
    }


def test_signal_metric_names_the_rule_used():
    assert _last([*_wavy(60), 90.0]).metrics["signal"] == "combined"
    assert _last([*_wavy(60), 90.0], params=replace(DEFAULT_PARAMS, signal="sma_gap")).metrics["signal"] == "sma_gap"
    assert _last([*_wavy(60), 90.0], params=replace(DEFAULT_PARAMS, signal="drawdown")).metrics["signal"] == "drawdown"


# --- touched level: the month's low, not the close ---------------------------


def test_touched_level_uses_intra_month_low_sma_mode():
    history = _wavy(60)
    probe = _last([*history, history[-1]])
    p4 = probe.level_prices["4x"]
    close = history[-1]
    v = _last([*history, close], lows=[None] * 60 + [p4 * 0.999])
    assert v.level == probe.level
    assert v.touched_level == 4
    # A low that stays above the 2X price touches nothing extra.
    p2 = probe.level_prices["2x"]
    v2 = _last([*history, close], lows=[None] * 60 + [max(p2 * 1.001, close * 0.9999)])
    assert v2.touched_level is None


def test_touched_level_uses_intra_month_low_drawdown_mode():
    params = replace(DEFAULT_PARAMS, signal="drawdown", min_months=3, cap4_before_months=None)
    v = _last([100.0, 100.0, 100.0, 95.0], params, lows=[None, None, None, 59.0])
    assert v.level == 1
    assert v.touched_level == 4
    v3 = _last([100.0, 100.0, 100.0, 95.0], params, lows=[None, None, None, 74.0])
    assert v3.touched_level == 3


def test_young_ticker_caps_touched_level_at_3x():
    params = replace(DEFAULT_PARAMS, signal="drawdown", min_months=3, cap4_before_months=24)
    v = _last([100.0, 100.0, 100.0, 95.0], params, lows=[None, None, None, 50.0])
    assert v.touched_level == 3
    assert v.level_prices["4x"] is None


def test_cap4_boundary_month():
    # cap4_before_months=24: month 24 (i + 1 == 24) is no longer capped.
    params = replace(DEFAULT_PARAMS, signal="drawdown", min_months=3, cap4_before_months=24)
    capped = _last([100.0] * 22 + [50.0], params)
    free = _last([100.0] * 23 + [50.0], params)
    assert capped.level == 3
    assert free.level == 4
    assert free.level_prices["4x"] == pytest.approx(60.0)


# --- trims -----------------------------------------------------------------


def test_trim_thresholds_are_inclusive():
    params = replace(
        DEFAULT_PARAMS,
        signal="drawdown",
        min_months=3,
        trim_sma_months=3,
        trim_light_gap=0.5,
        trim_strong_gap=1.0,
        trim_rsi_light=0.0,
        trim_rsi_strong=0.0,
    )
    # SMA3 of [x, x, c] with c / sma - 1 == gap exactly.
    light = _last([100.0, 100.0, 100.0, 100.0, 400.0], params)  # sma=200, gap=1.0
    assert light.metrics["trim_sma_gap"] == pytest.approx(1.0)
    assert light.level == LEVEL_STRONG_TRIM
    half = _last([100.0, 100.0, 100.0, 100.0, 250.0], params)  # sma=150, gap=2/3
    assert half.level == LEVEL_LIGHT_TRIM


def test_strong_trim_needs_rsi():
    params = replace(
        DEFAULT_PARAMS,
        signal="drawdown",
        min_months=3,
        trim_sma_months=3,
        trim_light_gap=0.5,
        trim_strong_gap=1.0,
        trim_rsi_light=0.0,
        trim_rsi_strong=101.0,
    )
    v = _last([100.0, 100.0, 100.0, 100.0, 400.0], params)
    assert v.level == LEVEL_LIGHT_TRIM


# --- RSI (Wilder) and trailing volatility, exact values -----------------------


def test_rsi_series_exact_wilder_values():
    out = _rsi_series([1.0, 2.0, 1.0, 2.0, 2.0], 2)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(50.0)  # avg gain 0.5, avg loss 0.5
    assert out[3] == pytest.approx(75.0)  # (0.5+1)/2=0.75 vs (0.5+0)/2=0.25
    assert out[4] == pytest.approx(100.0 - 100.0 / (1.0 + 0.375 / 0.125))


def test_rsi_series_all_gains_is_100_and_short_input_is_none():
    assert _rsi_series([1.0, 2.0, 3.0, 4.0], 2)[2:] == [100.0, 100.0]
    assert _rsi_series([1.0, 2.0], 2) == [None, None]
    assert _rsi_series([3.0, 2.0, 1.0], 2)[2] == pytest.approx(0.0)


def test_rsi_metric_reported_for_the_month():
    v = _last([*_wavy(60), 90.0])
    expected = _rsi_series([*_wavy(60), 90.0], DEFAULT_PARAMS.rsi_period)[-1]
    assert expected is not None
    assert v.metrics["rsi"] == pytest.approx(round(expected, 4))


def test_trailing_vol_is_annualised_sample_stdev_of_prior_log_returns():
    closes = _wavy(50)
    params = replace(DEFAULT_PARAMS, vol_lookback_months=36, vol_min_months=12)
    i = 45
    rets = [math.log(closes[j] / closes[j - 1]) for j in range(i - 36, i)]
    assert _trailing_vol(closes, i, params) == pytest.approx(statistics.stdev(rets) * math.sqrt(12))
    # Short history: from month 1, never month 0.
    rets_short = [math.log(closes[j] / closes[j - 1]) for j in range(1, 13)]
    assert _trailing_vol(closes, 13, params) == pytest.approx(statistics.stdev(rets_short) * math.sqrt(12))
    # Exactly vol_min_months returns are enough; one fewer is not.
    assert _trailing_vol(closes, 13, params) is not None
    assert _trailing_vol(closes, 12, params) is None


def test_vol_metric_and_ratio_reported():
    closes = [*_wavy(60), 90.0]
    v = _last(closes)
    vol = _trailing_vol(closes, 60, DEFAULT_PARAMS)
    assert vol is not None
    assert v.metrics["vol"] == pytest.approx(round(vol, 6))
    assert v.metrics["vol_ratio"] == pytest.approx(round(vol / DEFAULT_PARAMS.vol_ref, 6))


def test_current_verdict_respects_today():
    bars = _bars(_wavy(40))
    last_day = bars[-1].day
    assert current_verdict(bars, today=last_day).status == "forming"
    assert current_verdict(bars, today=date(last_day.year + 1, 1, 1)).status == "confirmed"
