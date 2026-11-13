"""A future reported period cannot anchor a deadline presented as observed history."""
from datetime import date, timedelta

from app.services import catalyst_calendar_service as service


def _payload(periods):
    return {'category': 'Large accelerated filer', 'fiscalYearEnd': '1231',
            'filings': {'recent': {'form': ['10-Q'] * len(periods), 'reportDate': periods}}}


def test_future_period_does_not_generate_a_deadline_from_unobserved_history():
    future = (date.today() + timedelta(days=366)).replace(month=12, day=31)
    assert service.filing_deadline_event(_payload([future.isoformat()]), 'EXAMPLE') is None


def test_future_row_does_not_replace_last_observed_period():
    observed = ['2025-03-31', '2025-06-30']
    future = (date.today() + timedelta(days=366)).replace(month=12, day=31).isoformat()
    expected = service.filing_deadline_event(_payload(observed), 'EXAMPLE')
    assert service.filing_deadline_event(_payload([*observed, future]), 'EXAMPLE') == expected
