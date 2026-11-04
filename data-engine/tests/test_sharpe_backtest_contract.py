from datetime import date

from app.services.dca_backtest import backtest_dca
from app.services.dca_signal_engine import DailyBar
from app.services.paper_trading_service import scoreboard


def bars(n=120):
    return [DailyBar(day=date(2010+i//12, 1+i%12, d), close=100+i+(i%5)*2)
            for i in range(n) for d in (2,20)]


def test_dca_reference_is_not_a_strategy_sharpe_or_irr_significance():
    out = backtest_dca(bars(), today=date(2030,1,1))
    diagnostic = out["sharpe_diagnostics"]
    assert diagnostic["strategy"]["status"] == "unavailable"
    assert diagnostic["strategy"]["reason"] == "missing_flow_adjusted_nav_series"
    ref = diagnostic["underlying_reference"]
    assert ref["frequency"] == "monthly"
    assert ref["periods_per_year"] == 12
    assert ref["basis"] == "underlying_month_end_price_returns_not_strategy_total_return"
    assert ref["validation_claim"] is False
    assert ref["n_observations"] == out["months"]-1
    assert ref["horizon"]["end"] == out["valued_at_date"]
    assert ref["risk_free_per_period"] == 0
    assert diagnostic["params_version"] == out["params_version"]


def test_open_month_excluded_from_reference_sample():
    closed = backtest_dca(bars(), today=date(2030,1,1))["sharpe_diagnostics"]["underlying_reference"]
    opened = backtest_dca(bars(), today=date(2019,12,25))["sharpe_diagnostics"]["underlying_reference"]
    assert opened["n_observations"] == closed["n_observations"]-1
    assert opened["horizon"]["end"] == "2019-11-20"


def test_missing_calendar_month_does_not_become_one_month_return():
    data = [b for b in bars() if not (b.day.year == 2017 and b.day.month == 6)]
    ref = backtest_dca(data, today=date(2030,1,1))["sharpe_diagnostics"]["underlying_reference"]
    assert ref["status"] == "invalid_series"
    assert ref["sharpe_per_period"] is None


def test_paper_closed_trades_are_not_periodic_observations():
    ref = scoreboard([])["sharpe_diagnostics"]
    assert ref["status"] == "unavailable"
    assert ref["reason"] == "missing_periodic_net_nav_series"
    assert ref["n_observations"] == 0
    assert ref["frequency"] is None
    assert ref["t_statistic"] is None
    assert ref["confidence_interval"] is None
