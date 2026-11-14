"""Large, same-unit forecast misses remain measured and carry a warning."""
from datetime import date

import pytest

from app.services.estimate_accuracy import Estimate, cases, measured_errors, summarize
from app.services.own_consensus import Actual, confidence_for


@pytest.mark.parametrize('actual', [400.0, 10.0, 0.0, -100.0])
def test_same_unit_revenue_misses_count_with_visible_warning(actual):
    items = cases(
        [Estimate('guia', 'revenue', 'fy2025', None, 100.0, None, date(2025, 1, 1))],
        {'revenue': {'fy2025': Actual('fy2025', date(2025, 12, 31), actual)}},
    )
    [item] = items
    assert item['excluded'] is None
    assert item['flags']
    [summary] = summarize(items)
    assert summary['n'] == 1 and summary['n_excluded'] == 0 and summary['n_extreme'] == 1
    assert summary['median_abs_error'] == abs(actual / 100 - 1)
    assert measured_errors(items) == {('guia', '≤1A'): [actual / 100 - 1]}


@pytest.mark.parametrize('actual', [0.1, 0.0001, 100_000.0, 100_000_000.0])
def test_scale_mismatch_stays_separate_and_visible(actual):
    items = cases(
        [Estimate('guia', 'revenue', 'fy2025', None, 100.0, None, date(2025, 1, 1))],
        {'revenue': {'fy2025': Actual('fy2025', date(2025, 12, 31), actual)}},
    )
    assert items[0]['excluded'].startswith('escala_distinta:')
    [summary] = summarize(items)
    assert summary['n'] == 0 and summary['n_excluded'] == 1
    assert measured_errors(items) == {}


@pytest.mark.parametrize('actual', [100 / 3, 100.0, 300.0])
def test_non_extreme_boundaries_keep_no_warning(actual):
    [item] = cases(
        [Estimate('guia', 'revenue', 'fy2025', None, 100.0, None, date(2025, 1, 1))],
        {'revenue': {'fy2025': Actual('fy2025', date(2025, 12, 31), actual)}},
    )
    assert item['excluded'] is None
    assert item['flags'] == []


def test_large_miss_cannot_disappear_from_confidence_samples():
    estimates = []
    actuals = {'revenue': {}}
    for year in range(2018, 2026):
        period = f'fy{year}'
        estimates.append(Estimate('guia', 'revenue', period, None, 100.0, None, date(year, 1, 1)))
        actuals['revenue'][period] = Actual(period, date(year, 12, 31), 400.0)
    items = cases(estimates, actuals)
    [summary] = summarize(items)
    assert summary['n'] == 8 and summary['n_excluded'] == 0
    assert summary['median_abs_error'] == 3.0
    errors = measured_errors(items)
    assert errors == {('guia', '≤1A'): [3.0] * 8}
    confidence = confidence_for('guia', '≤1A', errors)
    assert confidence['n'] == 8 and confidence['level'] == 'bajo'
    assert confidence['median_abs_error'] == 3.0


def test_unmatched_and_invalid_periods_still_skip():
    estimates = [
        Estimate('guia', 'eps', 'fy2025', None, 100.0, None, date(2025, 1, 1)),
        Estimate('guia', 'revenue', 'invalid', None, 100.0, None, date(2025, 1, 1)),
    ]
    assert cases(estimates, {'revenue': {'fy2025': Actual('fy2025', date(2025, 12, 31), 400.0)}}) == []
