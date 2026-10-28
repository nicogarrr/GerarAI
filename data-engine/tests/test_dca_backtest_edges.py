"""Backtest DCA: TIR sin raiz en el intervalo y barras corruptas que no contaminan."""
from datetime import date

from app.services.dca_backtest import backtest_dca, irr_monthly
from app.services.dca_signal_engine import DailyBar


def _bars(closes, start=date(2015, 1, 1)):
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


def test_irr_returns_none_when_npv_has_no_root_in_interval():
    # Flujos con ambos signos pero NPV negativo en ambos extremos: no hay TIR en [-50%, +50%].
    assert irr_monthly([-100.0, 1.0]) is None
    assert irr_monthly([-100.0, 1.0, 1.0, 1.0]) is None


def test_corrupt_bars_do_not_change_the_backtest():
    corrupt = [
        DailyBar(day=date(2017, 6, 10), close=0.0),
        DailyBar(day=date(2017, 6, 11), close=-5.0),
        DailyBar(day=date(2017, 6, 12), close=float("nan")),
    ]
    clean = backtest_dca(_bars(SERIES), today=date(2030, 1, 1))
    dirty = backtest_dca(_bars(SERIES) + corrupt, today=date(2030, 1, 1))
    assert dirty["available"] is True
    assert dirty["plans"] == clean["plans"]
    assert dirty["levels"] == clean["levels"]
    assert dirty["months"] == clean["months"]
