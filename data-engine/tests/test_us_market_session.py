"""Shared market-session rule uses New York dates and its legacy 16:30 cutoff."""
from datetime import UTC, datetime

import pytest

from app.services.us_market_session import session_open


@pytest.mark.parametrize(
    "instant, expected",
    [
        (datetime(2026, 11, 6, 21, 29, tzinfo=UTC), True),
        (datetime(2026, 11, 6, 21, 30, tzinfo=UTC), False),
        (datetime(2026, 11, 7, 17, 0, tzinfo=UTC), False),
        (datetime(2026, 11, 8, 17, 0, tzinfo=UTC), False),
        (datetime(2026, 11, 7, 0, 0, tzinfo=UTC), False),
        (datetime(2026, 11, 9, 17, 0, tzinfo=UTC), True),
    ],
)
def test_shared_new_york_session_cutoff_and_weekends(instant, expected):
    assert session_open(instant) is expected
