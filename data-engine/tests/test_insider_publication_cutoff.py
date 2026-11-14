"""A transaction was not observable before its filing was published."""
from datetime import date, timedelta

import pytest

from app.services import insider_feed
from app.services import insider_operations as operations
from app.services.ticker_ownership_signals import insider_signal
from tests.test_insider_operations import _filing, _seed_portfolio_and_watchlist, _tx, db  # noqa: F401


@pytest.mark.parametrize('reader', ['feed', 'operations', 'ownership'])
@pytest.mark.parametrize('published', ['tomorrow', 'today', 'missing'])
def test_publication_date_is_an_independent_cutoff(db, reader, published):
    _seed_portfolio_and_watchlist(db)
    today = date.today()
    filing = _filing(db, 'RKLB', f'publication-{reader}-{published}')
    filing.filing_date = {'tomorrow': (today + timedelta(days=1)).isoformat(),
                          'today': today.isoformat(), 'missing': None}[published]
    _tx(db, filing, fp_suffix='-1', insider='Known Insider', code='P', shares=10,
        price=10, value=100, tx_date=(today - timedelta(days=1)).isoformat())
    db.commit()
    visible = published != 'tomorrow'
    if reader == 'feed':
        result = insider_feed.build_feed(db, today=today)
        assert result['count'] == int(visible)
        assert result['totals']['buy_value'] == (100 if visible else 0)
        assert result['excluded_future_rows'] == int(not visible)
        assert len(result['transactions']) == int(visible)
    elif reader == 'operations':
        result = operations.insider_operations(db)
        assert len(result['companies']) == int(visible)
        assert result['excluded_future_rows'] == int(not visible)
    else:
        result = insider_signal(db, 'RKLB', as_of=today)
        assert result['status'] == ('ok' if visible else 'sin_datos')
