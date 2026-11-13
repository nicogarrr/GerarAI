"""A 52-week observed range cannot contain observations from the future."""
from datetime import date, timedelta

from app.services.key_stats_service import range_from_closes


def test_future_closes_do_not_change_range_or_session_coverage():
    today = date(2026, 11, 13)
    result = range_from_closes([
        (today - timedelta(days=20), 100), (today, 110),
        (today + timedelta(days=1), 1), (today + timedelta(days=2), 1000),
    ], today)
    assert result.low == 100
    assert result.high == 110
    assert result.sessions == 2
    assert result.high_date == today.isoformat()


def test_future_only_closes_are_not_an_observed_range():
    today = date(2026, 11, 13)
    assert range_from_closes([(today + timedelta(days=1), 100)], today) is None
