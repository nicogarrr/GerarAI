"""Backtest DCA plano vs niveles: sin look-ahead y con presupuesto honesto."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.dca_backtest import backtest_dca, irr_monthly
from app.services.dca_signal_engine import DailyBar


def _bars(closes: list[float], start: date = date(2015, 1, 1)) -> list[DailyBar]:
    """Dos barras por mes (dia 2 y dia 20) con el mismo cierre."""
    out = []
    y, m = start.year, start.month
    for c in closes:
        out.append(DailyBar(day=date(y, m, 2), close=c))
        out.append(DailyBar(day=date(y, m, 20), close=c))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


SERIES = (
    [100.0 + i for i in range(30)] + [90.0, 80.0, 70.0, 65.0, 70.0, 80.0] + [100.0 + 2 * i for i in range(12)]
)


def test_irr_monthly_matches_closed_form() -> None:
    assert irr_monthly([-100.0, 110.0]) == pytest.approx(1.1**12 - 1, rel=1e-6)
    assert irr_monthly([-100.0, 0.0]) is None


def test_levels_buy_more_in_the_dip_and_fixed_budget_uses_the_same_money() -> None:
    result = backtest_dca(_bars(SERIES), base_amount=100.0, today=date(2030, 1, 1))
    assert result["available"] is True
    plans = {p["key"]: p for p in result["plans"]}
    plain, levels, fixed = plans["plain"], plans["levels"], plans["fixed_budget"]
    assert plain["invested"] == 100.0 * result["months"]
    assert levels["invested"] > plain["invested"]  # aporta extra en 2X-4X
    assert levels["avg_cost"] < plain["avg_cost"]
    assert fixed["invested"] == pytest.approx(plain["invested"])
    assert fixed["deployed"] + fixed["cash_left"] == pytest.approx(plain["invested"])
    assert any(row["level"] >= 2 for row in result["levels"])
    assert result["hit_rates"]["rows"][0]["key"] == "2x-4x"


def test_no_look_ahead_future_bars_do_not_change_past_purchases() -> None:
    full = backtest_dca(_bars(SERIES), end="2017-12", today=date(2030, 1, 1))
    cut = backtest_dca(_bars(SERIES[:37]), end="2017-12", today=date(2030, 1, 1))
    assert full["plans"] == cut["plans"]
    assert full["levels"] == cut["levels"]


def test_range_and_insufficient_history() -> None:
    ranged = backtest_dca(_bars(SERIES), start="2017-01", end="2017-06", today=date(2030, 1, 1))
    assert ranged["first_signal"] == "2017-01" and ranged["last_signal"] == "2017-06"
    assert ranged["months"] == 6
    short = backtest_dca(_bars(SERIES[:13]), today=date(2030, 1, 1))
    assert short["available"] is False and "insuficiente" in short["reason"]
    with pytest.raises(ValueError):
        backtest_dca(_bars(SERIES), base_amount=0)


def test_valuation_says_when_the_month_is_still_open() -> None:
    """Valorar a mitad de mes no es «el cierre de 2018-12»: se da la fecha y se marca abierto."""
    open_month = backtest_dca(_bars(SERIES), today=date(2018, 12, 25))
    assert open_month["valued_at_period"] == "2018-12"
    assert open_month["valued_at_date"] == "2018-12-20"
    assert open_month["valued_month_complete"] is False
    closed = backtest_dca(_bars(SERIES), today=date(2030, 1, 1))
    assert closed["valued_at_date"] == "2018-12-20"
    assert closed["valued_month_complete"] is True
