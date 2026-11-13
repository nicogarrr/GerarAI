"""A reference session cannot use a later close to compute its return."""
from datetime import UTC, date, datetime

from app.services import market_themes as mt


def candles():
    days = [date(2025, 12, 31), date(2026, 9, 9), date(2026, 10, 9), date(2026, 12, 25)]
    return {'s': 'ok', 't': [int(datetime.combine(day, datetime.min.time(), tzinfo=UTC).timestamp()) for day in days],
            'c': [100, 100, 120, 500]}


def test_symbol_return_ignores_closes_later_than_reference_session():
    result = mt.symbol_returns(candles(), date(2026, 10, 9))
    assert result['last_date'] == date(2026, 10, 9)
    assert round(result['ytd'], 6) == 20
    assert round(result['m1'], 6) == 20


def test_several_bad_future_rows_cannot_move_the_reference_into_the_future():
    result = mt.compute_themes({key: candles() for key in ('A', 'B', 'C')},
        [{'id': 'test', 'name': 'Test', 'tickers': ['A', 'B', 'C']}],
        generated_at=datetime(2026, 10, 9, 23, tzinfo=UTC))
    assert result['as_of'] == '2026-10-09'
    assert result['themes'][0]['ytd']['pct'] == 20
