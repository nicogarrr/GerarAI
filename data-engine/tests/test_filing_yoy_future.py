"""A future reported period is not a completed financial report."""
from datetime import date, timedelta

from app.services.filing_yoy_service import comparison
from tests.test_filing_yoy_service import db, doc  # noqa: F401


def test_future_report_does_not_replace_latest_observed_period(db):
    today = date.today()
    current = today - timedelta(days=60)
    prior = current.replace(year=current.year - 1)
    observed = doc(db, current.isoformat(), n=1)
    doc(db, prior.isoformat(), n=2)
    future = today + timedelta(days=300)
    doc(db, future.isoformat(), n=3)
    result = comparison(db, db.info['company_id'], '10-K', 1)
    assert result['current']['document_id'] == observed.id
    assert result['total'] == 2


def test_only_future_periods_are_not_presented_as_reported(db):
    doc(db, (date.today() + timedelta(days=300)).isoformat(), n=1)
    result = comparison(db, db.info['company_id'], '10-K', 1)
    assert result['status'] == 'insufficient_data'
    assert result['total'] == 0
