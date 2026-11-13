"""Invalid official closes are unknown, never negative or non-finite prices."""
from datetime import date

import pytest

from app.services import market_change as mc
from tests.test_market_change_latest_by_index import _close, _company, db  # noqa: F401


@pytest.mark.parametrize('last', ['0', 'Infinity'])
def test_invalid_latest_close_has_no_price_or_return(db, last):
    company = _company(db, 'BAD')
    _close(db, company, date(2026, 10, 29), '100')
    _close(db, company, date(2026, 10, 30), last)
    db.commit()
    rows, _, _ = mc.compute_session_changes(db)
    assert rows[0]['price'] is None
    assert rows[0]['change_pct'] is None
    assert mc.ticker_close_change(db, company.id) is None


@pytest.mark.parametrize('previous', ['Infinity'])
def test_invalid_previous_close_does_not_create_return(db, previous):
    company = _company(db, 'BAD')
    _close(db, company, date(2026, 10, 29), previous)
    _close(db, company, date(2026, 10, 30), '100')
    db.commit()
    rows, _, _ = mc.compute_session_changes(db)
    assert rows[0]['price'] == 100
    assert rows[0]['change_pct'] is None
    assert rows[0]['previous_close'] is None
    assert mc.ticker_close_change(db, company.id) is None
