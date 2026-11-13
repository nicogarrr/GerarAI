"""Future trades must not populate the observed insider feed."""
from datetime import date, timedelta

from app.services.insider_feed import build_feed
from tests.test_insider_operations import _filing, _seed_portfolio_and_watchlist, _tx, db  # noqa: F401


def test_future_trade_is_not_in_feed_totals_or_signal_inputs(db, monkeypatch):
    _seed_portfolio_and_watchlist(db)
    filing = _filing(db, 'RKLB', '0001-26-000019')
    today = date.today()
    for suffix, day, value in [('-real', today.isoformat(), 100), ('-future', (today + timedelta(days=1)).isoformat(), 900)]:
        _tx(db, filing, fp_suffix=suffix, insider='Person', code='P', shares=10, price=10, value=value, tx_date=day)
    inputs = []
    monkeypatch.setattr('app.services.insider_feed.insider_service.detect_signals', lambda rows: inputs.extend(rows) or [])
    result = build_feed(db, today=today)
    assert result['count'] == 1
    assert result['totals']['buy_count'] == 1
    assert result['totals']['buy_value'] == 100
    assert len(inputs) == 1
    assert result['excluded_future_rows'] == 1
