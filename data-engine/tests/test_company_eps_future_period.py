"""Future or invalid fiscal periods cannot be displayed as actual EPS history."""
from datetime import date

import pytest

from app.services.company_events_service import CompanyEventsService
from tests.test_company_events_service import db  # noqa: F401


@pytest.mark.parametrize('period', ['2026-12-31', 'not-a-date'])
def test_future_or_invalid_period_does_not_displace_real_eps(db, period):
    svc = CompanyEventsService(db)
    rows = [
        {'period': '2026-09-30', 'actual': 2, 'estimate': 1.5},
        {'period': period, 'actual': 999, 'estimate': 999},
    ]
    result = svc._history([], rows, date(2026, 11, 13))
    assert [row['period'] for row in result] == ['2026-09-30']
    assert result[0]['eps_actual'] == 2
