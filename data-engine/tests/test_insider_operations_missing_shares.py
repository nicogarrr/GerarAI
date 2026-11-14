"""Sin cantidades completas no existe precio medio verificable."""
from datetime import date

import pytest

from app.services.insider_operations import insider_operations
from tests.test_insider_operations import _filing, _seed_portfolio_and_watchlist, _tx, db  # noqa: F401


@pytest.mark.parametrize('missing_value', [500.0, None])
def test_unknown_shares_do_not_produce_a_fake_weighted_average(db, missing_value):  # noqa: F811
    _seed_portfolio_and_watchlist(db)
    filing = _filing(db, 'RKLB', '0001-26-000111')
    for suffix, shares, value in [('-1', 100.0, 1000.0), ('-2', None, missing_value)]:
        _tx(db, filing, fp_suffix=suffix, insider='Fixture', code='S', shares=shares,
            price=None, value=value, tx_date=date.today().isoformat())
    company = insider_operations(db)['companies'][0]
    for side in (company['totals']['sell'], company['insiders'][0]['sell']):
        assert side['avg_price'] is None
        assert side['rows_without_shares'] == 1
        assert side['value'] == 1000.0 + (missing_value or 0)
    assert company['totals']['buy']['rows_without_shares'] == 0
