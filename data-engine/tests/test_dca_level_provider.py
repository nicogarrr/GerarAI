"""Compatibilidad del motor DCA con el esqueleto de avisos 1-4 (PR #2258)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from app.services.dca_level_provider import DcaEngineLevelProvider, reading_level
from app.services.dca_signal_engine import NICO_V0_PARAMS, DailyBar, evaluate_series


def _bars(closes: list[float]) -> list[DailyBar]:
    out = []
    y, m = 2020, 1
    for c in closes:
        out.append(DailyBar(date(y, m, 15), c))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


PARAMS = replace(NICO_V0_PARAMS, signal="drawdown", dd_thresholds=(0.15, 0.25, 0.40), min_months=3, version="test-v1")


def test_reading_level_maps_trims_to_level_one() -> None:
    rising = evaluate_series(_bars([100 * 1.06**i for i in range(40)]), params=replace(NICO_V0_PARAMS, signal="drawdown", min_months=15), month_complete=True)[-1]
    assert rising.level < 0
    assert reading_level(rising) == 1


def test_provider_returns_none_without_data() -> None:
    provider = DcaEngineLevelProvider(load_bars=lambda _t: None, params=PARAMS)
    assert provider.verdict("UBER") is None


def test_provider_reading_is_valid_for_entry_level_skeleton() -> None:
    ela = pytest.importorskip("app.services.entry_level_alerts")
    bars = _bars([100.0] * 6 + [59.0])
    provider = DcaEngineLevelProvider(load_bars=lambda _t: (bars, "yfinance"), params=PARAMS, today=bars[-1].day)
    reading = provider.read("uber")
    assert reading.ticker == "UBER" and reading.level == 4
    assert reading.status == "provisional" and reading.model_version == "test-v1"
    events, state = ela.plan_events(1, [reading], {})
    assert len(events) == 1 and state == {"UBER": 4}
