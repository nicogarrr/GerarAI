"""An analyst estimate count cannot be fractional or negative."""
from datetime import date

import pytest

from app.services.connectors.earnings_calendar import normalize_earnings_row


@pytest.mark.parametrize('value', ['-1', '1.5', -2, 2.5])
def test_unverifiable_estimate_counts_are_unknown(value):
    row = normalize_earnings_row({'symbol': 'EXAMPLE', 'noOfEsts': value}, date(2026, 11, 13))
    assert row['n_estimates'] is None


@pytest.mark.parametrize('value,expected', [('0', 0), ('12', 12), ('1,234', 1234)])
def test_nonnegative_integral_counts_are_preserved(value, expected):
    assert normalize_earnings_row({'symbol': 'EXAMPLE', 'noOfEsts': value}, date(2026, 11, 13))['n_estimates'] == expected
