"""13F report periods must have occurred before the filing was submitted."""
from app.services.connectors.form13f_dataset import parse_dataset
from tests.test_institutional_holders import APPLE, _info, _zip


def _parse(filed, period):
    return parse_dataset(_zip([f'A\t{filed}\t13F-HR\t1\t{period}'],
                              ['A\t\t\t\t\tManager'], [_info('A', APPLE, 100)]), {APPLE})


def test_report_period_after_filing_is_not_observed_holdings():
    assert _parse('13-AUG-2026', '30-SEP-2026').filings == {}


def test_future_filing_does_not_create_observed_holdings():
    assert _parse('13-AUG-2099', '30-JUN-2099').filings == {}


def test_observed_quarter_before_filing_is_preserved():
    assert _parse('13-AUG-2026', '30-JUN-2026').filings['A'].shares[APPLE] == 100
