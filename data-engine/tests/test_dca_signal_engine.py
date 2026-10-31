"""Tests del motor DCA (puro, sin DB): niveles, mes en formacion y no look-ahead."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.services.dca_signal_engine import (
    DEFAULT_PARAMS,
    LEVEL_LIGHT_TRIM,
    LEVEL_STRONG_TRIM,
    NICO_V0_PARAMS,
    NICO_V1_PARAMS,
    ZONES,
    DailyBar,
    DcaParams,
    current_verdict,
    evaluate_series,
    monthly_closes,
)


def _month_end_bars(closes: list[float], start: date = date(2018, 1, 1)) -> list[DailyBar]:
    """Una barra diaria por mes (dia 15) con el cierre indicado."""
    bars = []
    y, m = start.year, start.month
    for c in closes:
        bars.append(DailyBar(day=date(y, m, 15), close=c))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return bars


def test_monthly_closes_uses_last_daily_close_and_min_low() -> None:
    d0 = date(2024, 3, 1)
    bars = [
        DailyBar(day=d0 + timedelta(days=i), close=100 + i, low=99 + i) for i in range(5)
    ] + [DailyBar(day=date(2024, 4, 2), close=50, low=None)]
    months = monthly_closes(bars)
    assert months[0] == ("2024-03", date(2024, 3, 5), 104.0, 99.0)
    assert months[1] == ("2024-04", date(2024, 4, 2), 50.0, 50.0)


def test_monthly_closes_skips_invalid_prices() -> None:
    bars = [DailyBar(date(2024, 1, 2), 0.0), DailyBar(date(2024, 1, 3), float("nan")), DailyBar(date(2024, 1, 4), 10.0)]
    assert monthly_closes(bars) == [("2024-01", date(2024, 1, 4), 10.0, 10.0)]


def test_short_history_returns_nothing() -> None:
    params = replace(NICO_V0_PARAMS, min_months=24)
    assert evaluate_series(_month_end_bars([100.0] * 23), params=params) == []
    assert current_verdict(_month_end_bars([100.0] * 23), params=params) is None


def test_levels_follow_drawdown_thresholds() -> None:
    params = replace(NICO_V0_PARAMS, signal="drawdown", dd_thresholds=(0.15, 0.25, 0.40), min_months=3, high_lookback_months=36)
    base = [100.0] * 5
    cases = {90.0: 1, 84.0: 2, 74.0: 3, 59.0: 4}
    for close, expected in cases.items():
        verdict = evaluate_series(_month_end_bars([*base, close]), params=params, month_complete=True)[-1]
        assert verdict.level == expected, (close, verdict)
        assert verdict.zone == ZONES[expected]


def test_sma_gap_signal_levels() -> None:
    params = replace(NICO_V0_PARAMS, signal="sma_gap", sma_months=4, gap_thresholds=(0.0, 0.05, 0.10), min_months=4)
    # SMA de los 4 ultimos cierres incluye el propio mes.
    series = evaluate_series(_month_end_bars([100.0, 100.0, 100.0, 70.0]), params=params, month_complete=True)
    v = series[-1]
    # sma = 92.5 -> gap = 1 - 70/92.5 = 24 % -> 4X
    assert v.level == 4
    assert v.metrics["sma"] == pytest.approx(92.5)


def test_forming_vs_confirmed_status() -> None:
    bars = _month_end_bars([100.0] * 30)
    params = replace(NICO_V0_PARAMS, min_months=24)
    last_day = bars[-1].day
    forming = evaluate_series(bars, params=params, today=last_day)
    assert forming[-1].status == "forming"
    assert all(v.status == "confirmed" for v in forming[:-1])
    next_month = date(last_day.year + (last_day.month == 12), last_day.month % 12 + 1, 1)
    confirmed = evaluate_series(bars, params=params, today=next_month)
    assert confirmed[-1].status == "confirmed"


def test_no_look_ahead_past_verdicts_do_not_change() -> None:
    import math

    closes = [100 * (1 + 0.3 * math.sin(i / 5)) * (1 + i / 200) for i in range(120)]
    bars = _month_end_bars(closes)
    full = {v.period: v for v in evaluate_series(bars, month_complete=True)}
    for cut in range(40, 120, 7):
        partial = evaluate_series(bars[:cut], month_complete=True)
        for v in partial:
            other = full[v.period]
            assert v.level == other.level, v.period
            assert v.metrics == other.metrics, v.period


def test_trims_require_extension_and_rsi() -> None:
    params = replace(NICO_V0_PARAMS, 
        signal="drawdown",
        min_months=15,
        sma_months=10,
        trim_light_gap=0.25,
        trim_strong_gap=0.40,
        trim_rsi_light=75,
        trim_rsi_strong=85,
    )
    # Subida casi lineal y fuerte: RSI alto y precio muy por encima de su SMA.
    closes = [100 * (1.06**i) for i in range(40)]
    v = evaluate_series(_month_end_bars(closes), params=params, month_complete=True)[-1]
    assert v.level in (LEVEL_LIGHT_TRIM, LEVEL_STRONG_TRIM)
    flat = evaluate_series(_month_end_bars([100.0] * 40), params=params, month_complete=True)[-1]
    assert flat.level == 1


def test_level_prices_are_consistent_with_levels() -> None:
    params = replace(NICO_V0_PARAMS, signal="drawdown", dd_thresholds=(0.15, 0.25, 0.40), min_months=3)
    v = evaluate_series(_month_end_bars([100.0] * 5 + [95.0]), params=params, month_complete=True)[-1]
    assert v.level_prices == {"2x": pytest.approx(85.0), "3x": pytest.approx(75.0), "4x": pytest.approx(60.0)}
    # Cerrar justo en el precio de 3X da 3X.
    v3 = evaluate_series(_month_end_bars([100.0] * 5 + [75.0]), params=params, month_complete=True)[-1]
    assert v3.level == 3


def test_as_dict_is_json_friendly() -> None:
    import json

    v = current_verdict(_month_end_bars([100.0] * 30), today=date(2030, 1, 1))
    assert v is not None
    json.dumps(v.as_dict())


def test_hit_rates_counts_only_confirmed_months_and_future_closes() -> None:
    from app.services.dca_signal_engine import hit_rates

    params = replace(NICO_V0_PARAMS, signal="drawdown", dd_thresholds=(0.15, 0.25, 0.40), min_months=3)
    # 100 x5, caida a 80 (2X), luego recupera a 120 y se queda.
    closes = [100.0] * 5 + [80.0] + [120.0] * 10
    bars = _month_end_bars(closes)
    out = hit_rates(bars, params=params, horizons=(3, 12), today=bars[-1].day)
    # El ultimo mes esta en formacion: no cuenta.
    assert out["months_completed"] == len(closes) - 2 - 1
    row = {r["key"]: r for r in out["rows"]}["2x"]
    assert row["signal_months"] == 1
    c3, c12 = row["cells"]
    assert c3["months"] == 1 and c3["pct_higher"] == 1.0 and c3["avg_return"] == pytest.approx(0.5)
    # A 12 meses no hay mes confirmado aun: sin dato, no se inventa.
    assert c12["months"] == 0 and c12["pct_higher"] is None
    assert {r["key"]: r for r in out["rows"]}["2x-4x"]["signal_months"] == 1


def test_hit_rates_no_look_ahead() -> None:
    import math

    from app.services.dca_signal_engine import hit_rates

    closes = [100 * (1 + 0.35 * math.sin(i / 4)) for i in range(90)]
    bars = _month_end_bars(closes)
    full = hit_rates(bars, today=date(2040, 1, 1))
    cut = hit_rates(bars[:60], today=date(2040, 1, 1))
    # Mas historia solo puede anadir meses con resultado, nunca cambiar el nivel de uno pasado.
    for rf, rc in zip(full["rows"], cut["rows"], strict=True):
        assert rf["signal_months"] >= rc["signal_months"]


def test_nico_v2_defaults_to_combined() -> None:
    # La formula por defecto es la combinada (backtest comparativo 31-oct-2026);
    # la vigente hasta entonces se conserva en NICO_V1_PARAMS.
    assert DEFAULT_PARAMS.signal == "combined" and DEFAULT_PARAMS.version == "nico-v2"
    assert NICO_V1_PARAMS.signal == "sma_gap" and NICO_V1_PARAMS.version == "nico-v1"
    assert NICO_V0_PARAMS.signal == "sma_gap" and NICO_V0_PARAMS.version == "nico-v0"


def test_nico_v1_defaults_and_volatility_adjustment() -> None:
    assert NICO_V1_PARAMS.version == "nico-v1"
    assert NICO_V1_PARAMS.sma_months == 30 and NICO_V1_PARAMS.gap_thresholds == (0.0, 0.10, 0.20)
    # Serie tranquila (vol baja) vs serie agitada con el mismo descuento final:
    calm = [100.0 * (1.0 + 0.02 * ((-1) ** i)) for i in range(40)]
    wild = [100.0 * (1.0 + 0.25 * ((-1) ** i)) for i in range(40)]
    v_calm = evaluate_series(_month_end_bars([*calm, 80.0]), params=NICO_V1_PARAMS, month_complete=True)[-1]
    v_wild = evaluate_series(_month_end_bars([*wild, 80.0]), params=NICO_V1_PARAMS, month_complete=True)[-1]
    assert v_calm.metrics["vol"] < 0.30 < v_wild.metrics["vol"]
    # La misma caida bajo la SMA pesa mas en un valor tranquilo.
    assert v_calm.level > v_wild.level
    assert v_calm.metrics["adj_gap"] > v_wild.metrics["adj_gap"]
    # El precio de cada nivel es exacto: cerrar en el precio 2X da al menos 2X.
    p2 = v_wild.level_prices["2x"]
    assert p2 is not None
    at = evaluate_series(_month_end_bars([*wild, p2 * 0.999]), params=NICO_V1_PARAMS, month_complete=True)[-1]
    assert at.level >= 2


def test_nico_v1_young_ticker_uses_available_sma_and_caps_4x() -> None:
    closes = [100.0] * 14 + [40.0]  # 15 meses: SMA de 15 meses, sin 4X antes de 24
    verdict = evaluate_series(_month_end_bars(closes), month_complete=True)[-1]
    assert verdict.metrics["sma_months_used"] == 15
    assert verdict.level == 3


def test_young_series_never_shows_4x_price_or_touch() -> None:
    """Antes de 24 meses no hay 4X: ni nivel, ni precio de 4X, ni "toco 4X"."""
    closes = [100.0 if i % 2 == 0 else 105.0 for i in range(19)] + [40.0]
    bars = _month_end_bars(closes)
    bars[-1] = DailyBar(day=bars[-1].day, close=40.0, low=30.0)
    v = evaluate_series(bars, month_complete=True)[-1]
    assert v.metrics["months_of_history"] == 20
    assert v.level == 3
    assert v.level_prices["4x"] is None
    assert v.level_prices["3x"] is not None
    assert v.touched_level is None


def test_mature_series_keeps_4x_price() -> None:
    closes = [100.0 if i % 2 == 0 else 105.0 for i in range(29)] + [40.0]
    v = evaluate_series(_month_end_bars(closes), month_complete=True)[-1]
    assert v.level == 4
    assert v.level_prices["4x"] is not None


def test_flat_history_does_not_turn_one_percent_drop_into_4x() -> None:
    bars = _month_end_bars([100.0] * 48 + [99.0], start=date(2022, 1, 1))
    verdict = current_verdict(bars, today=date(2026, 2, 1))
    assert verdict is not None
    assert verdict.metrics["vol"] == 0.0
    assert verdict.metrics["vol_ratio"] == 1.0
    assert verdict.level != 4
    assert verdict.metrics["adj_gap"] is not None
    assert verdict.metrics["adj_gap"] < 0.02


def test_near_zero_volatility_has_no_artificial_4x() -> None:
    bars = _month_end_bars([100.0 + (n % 2) * 0.1 for n in range(48)] + [99.0])
    verdict = current_verdict(bars, today=date(2022, 2, 1))
    assert verdict is not None
    assert verdict.level != 4
    assert verdict.metrics["vol_ratio"] == 1.0


# --- Modo combinado (nico-v2): max(sma_gap, drawdown) -------------------------


def _parabolic_crash() -> list[float]:
    """Subida parabolica y caida del 27%: la SMA queda lejos, el drawdown manda."""
    base = [100.0 + i for i in range(30)]  # 100 -> 129
    spike = [150.0, 180.0, 210.0, 240.0, 260.0, 280.0]
    return [*base, *spike, 280.0 * 0.73]


def test_combined_drawdown_binds_after_parabolic_rise() -> None:
    verdict = evaluate_series(_month_end_bars(_parabolic_crash()), month_complete=True)[-1]
    # La caida desde el maximo es >= 25% (3X por drawdown) pero el cierre sigue
    # muy por encima de la SMA de 30 meses (1X por sma_gap).
    assert verdict.metrics["level_drawdown"] == 3
    assert verdict.metrics["level_sma_gap"] == 1
    assert verdict.level == 3
    assert verdict.metrics["binding"] == "drawdown"
    assert verdict.metrics["signal"] == "combined"


def test_combined_sma_binds_on_slow_bleed() -> None:
    # Sangrado lento con volatilidad realista (~30% anualizada, ajuste neutro):
    # <15% bajo el maximo (1X por drawdown) pero bajo la SMA (>=2X por gap).
    # Plano con oscilacion (vol realista) y descenso final al 91.5: 12.9% bajo
    # el maximo (1X por drawdown) pero 8.5% bajo la SMA (~2X por gap).
    closes = [95.0 if i % 2 else 105.0 for i in range(35)]
    closes += [97.0, 95.0, 93.0, 92.0, 91.5]
    verdict = evaluate_series(_month_end_bars(closes), month_complete=True)[-1]
    assert verdict.metrics["level_drawdown"] == 1
    assert verdict.metrics["level_sma_gap"] >= 2
    assert verdict.level == verdict.metrics["level_sma_gap"]
    assert verdict.metrics["binding"] == "sma_gap"


def test_combined_binding_tie_declared() -> None:
    # Ambas familias en 1X: precio sobre la SMA y caida menor del 15%.
    closes = [100.0 + i * 2 for i in range(39)] + [100.0 + 38 * 2 - 5]
    verdict = evaluate_series(_month_end_bars(closes), month_complete=True)[-1]
    assert verdict.metrics["level_sma_gap"] == 1
    assert verdict.metrics["level_drawdown"] == 1
    assert verdict.metrics["binding"] == "empate"
    assert verdict.level == 1


def test_combined_level_price_is_the_first_reached() -> None:
    verdict = evaluate_series(_month_end_bars(_parabolic_crash()), month_complete=True)[-1]
    # El 3X lo fija el drawdown: precio = 75% del maximo previo (280 * 0.75).
    assert verdict.level_prices["3x"] == pytest.approx(210.0, abs=0.01)
    # Cerrar en ese precio activa al menos 3X (el precio mostrado es real).
    at = evaluate_series(
        _month_end_bars([*_parabolic_crash()[:-1], 210.0 * 0.999]), month_complete=True
    )[-1]
    assert at.level >= 3


def test_combined_young_ticker_without_sma_uses_drawdown() -> None:
    params = DcaParams(signal="combined", sma_min_months=None)  # exige 30 meses de SMA
    closes = [100.0] * 14 + [70.0]  # 15 meses: sin SMA; drawdown 30% -> 3X
    verdict = evaluate_series(_month_end_bars(closes), params=params, month_complete=True)[-1]
    assert verdict.metrics["level_sma_gap"] is None
    assert verdict.metrics["level_drawdown"] == 3
    assert verdict.metrics["binding"] == "drawdown"
    assert verdict.level == 3


def test_combined_cap4_before_months_still_caps() -> None:
    closes = [100.0] * 14 + [50.0]  # 15 meses, drawdown 50% -> 4X, pero cap en 24m
    verdict = evaluate_series(_month_end_bars(closes), month_complete=True)[-1]
    assert verdict.metrics["level_drawdown"] == 4
    assert verdict.level == 3
    assert verdict.level_prices["4x"] is None


def test_combined_touched_is_max_of_families() -> None:
    history = _parabolic_crash()
    probe = evaluate_series(_month_end_bars(history), month_complete=True)[-1]
    close = history[-1]
    # Minimo intrames que toca 4X por drawdown (60% del maximo previo = 168).
    bars = _month_end_bars(history)
    bars[-1] = DailyBar(day=bars[-1].day, close=close, low=280.0 * 0.60 * 0.999)
    verdict = evaluate_series(bars, month_complete=True)[-1]
    assert verdict.touched_level == 4
    assert probe.touched_level is None or probe.touched_level < 4
