"""Missing numeric facts stay null; invalid values must not break JSON output."""
import json
from datetime import date

import pytest

from app.services.connectors.earnings_calendar import normalize_dividend_row, normalize_earnings_row


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-inf', '1e999'])
def test_nonfinite_earnings_and_dividend_values_are_unknown(value):
    day = date(2026, 11, 13)
    earnings = normalize_earnings_row({'symbol': 'ABC', 'epsForecast': value,
                                      'noOfEsts': value, 'marketCap': value}, day)
    dividend = normalize_dividend_row({'symbol': 'ABC', 'dividend_Rate': value}, day)
    for field in ('eps_forecast', 'n_estimates', 'market_cap'):
        assert earnings[field] is None
    assert dividend['amount'] is None
    json.dumps([earnings, dividend], allow_nan=False)


def test_negative_eps_and_zero_amount_are_not_discarded():
    day = date(2026, 11, 13)
    assert normalize_earnings_row({'epsForecast': '($0.05)'}, day)['eps_forecast'] == -0.05
    assert normalize_dividend_row({'amount': '0'}, day)['amount'] == 0
