"""The persisted operations window cannot include tomorrow's trades."""
from datetime import date, timedelta

from app.services.insider_operations import insider_operations
from tests.test_insider_operations import _filing, _seed_portfolio_and_watchlist, _tx, db  # noqa: F401


def test_future_trade_is_excluded_and_counted_without_hiding_real_trade(db):
    _seed_portfolio_and_watchlist(db)
    filing = _filing(db, 'RKLB', '0001-26-000009')
    today = date.today().isoformat()
    for suffix, day, value in [('-real', today, 100), ('-future', (date.today() + timedelta(days=1)).isoformat(), 900)]:
        _tx(db, filing, fp_suffix=suffix, insider='Person', code='P', shares=10, price=10, value=value, tx_date=day)
    result = insider_operations(db)
    row = result['companies'][0]
    assert row['totals']['buy']['value'] == 100
    assert row['totals']['buy']['trades'] == 1
    assert row['period'] == {'from': today, 'to': today}
    assert result['excluded_future_rows'] == 1


def test_future_only_trade_is_not_current_activity(db):
    _seed_portfolio_and_watchlist(db)
    filing = _filing(db, 'RKLB', '0001-26-000008')
    _tx(db, filing, fp_suffix='-future', insider='Person', code='P', shares=10, price=10,
        value=100, tx_date=(date.today() + timedelta(days=1)).isoformat())
    result = insider_operations(db)
    assert result['companies'] == []
    assert result['excluded_future_rows'] == 1
