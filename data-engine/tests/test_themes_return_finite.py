"""Finite positive closes may still yield nonfinite computed returns."""
from datetime import UTC, date, datetime

import pytest

from app.services import market_themes as mt

SESSION = date(2026, 11, 13)


def candles(base, last):
    days = [date(2025, 12, 31), date(2026, 10, 13), SESSION]
    return {'s': 'ok', 't': [int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()) for d in days], 'c': [base, base, last]}


@pytest.mark.parametrize('base,last', [(1e-308, 1e308), (1, 1e307)])
def test_computed_overflow_is_unknown(base, last):
    result = mt.symbol_returns(candles(base, last), SESSION)
    assert result == {'last_date': SESSION, 'ytd': None, 'm1': None}


def test_overflow_never_contributes_to_coverage_or_rank():
    basket = [{'id': 'example', 'name': 'Example', 'tickers': ['A', 'B', 'C']}]
    result = mt.compute_themes({t: candles(1e-308, 1e308) for t in ['A', 'B', 'C']}, basket, generated_at=datetime(2026, 11, 14, tzinfo=UTC))
    assert result['symbols_with_data'] == 0
    theme = result['themes'][0]
    for metric in ['ytd', 'm1']:
        assert theme[metric] == {'pct': None, 'n': 0}
    assert theme['rank'] is None
    assert theme['rank_1m'] is None
    assert theme['hot'] is False
    assert theme['turn'] is None


@pytest.mark.parametrize('base,last,expected', [(100, 100, 0), (100, 120, 20), (100, 50, -50)])
def test_finite_zero_positive_and_negative_returns_preserved(base, last, expected):
    result = mt.symbol_returns(candles(base, last), SESSION)
    assert result['ytd'] == pytest.approx(expected)
    assert result['m1'] == pytest.approx(expected)
