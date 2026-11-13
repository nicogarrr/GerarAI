"""Malformed Yahoo fields do not fabricate beta/ranges or break dates."""
from datetime import date

import pytest

from app.services.key_stats_service import normalize_yahoo_info


@pytest.mark.parametrize('value', [True, False, 10**400])
def test_invalid_numbers_are_unknown(value):
    result = normalize_yahoo_info({'beta': value, 'fiftyTwoWeekLow': value,
                                   'fiftyTwoWeekHigh': 100}, date(2026, 11, 13))
    assert result['beta'] is None
    assert result['low_52w'] is None and result['high_52w'] is None


@pytest.mark.parametrize('value', [1e300, 10**400, True, float('inf'), 'bad'])
def test_invalid_dates_do_not_break_other_real_fields(value):
    result = normalize_yahoo_info({'beta': 1.25, 'earningsTimestamp': value,
                                   'exDividendDate': value}, date(2026, 11, 13))
    assert result['beta'] == 1.25
    assert result['earnings'] is None and result['ex_dividend'] is None
