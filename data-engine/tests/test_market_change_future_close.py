"""Future official-close rows cannot become the current market session."""
from datetime import date, timedelta

from app.services import market_change as mc
from tests.test_market_change_latest_by_index import _close, _company, db  # noqa: F401


def test_future_rows_do_not_replace_latest_real_session_or_close(db):
    today = date.today()
    while today.weekday() >= 5:
        today -= timedelta(days=1)
    previous = today - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    future = today + timedelta(days=14)
    company = _company(db, 'REAL')
    _close(db, company, previous, '100')
    _close(db, company, today, '110')
    _close(db, company, future, '999')
    db.commit()
    assert mc.common_sessions(db) == (today, previous)
    full, _, session = mc.compute_session_changes(db)
    subset, _, _ = mc.compute_session_changes(db, ['REAL'])
    assert session == today
    assert full == subset
    assert full[0]['price'] == 110
    assert full[0]['change_pct'] == 10
    assert mc.ticker_close_change(db, company.id)['date'] == today.isoformat()


def test_future_only_company_is_not_a_current_quote(db):
    company = _company(db, 'FUT')
    _close(db, company, date.today() + timedelta(days=14), '999')
    db.commit()
    assert mc.common_sessions(db) == (None, None)
    assert mc.compute_session_changes(db) == ([], 0, None)
    assert mc.ticker_close_change(db, company.id) is None
