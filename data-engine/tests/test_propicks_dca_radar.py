from dataclasses import replace
from datetime import date

import pytest

from app.services.propicks_dca_radar import PAGE_SIZE, UNIVERSE_TARGET, RadarPrice, evaluate_candidate


def series():
    return [RadarPrice(date(2023 + i // 12, i % 12 + 1, 20), 100 + i, 100 + i, 'USD', 'official') for i in range(36)]


def evaluate(rows, **kwargs):
    return evaluate_candidate(rows, as_of=date(2025, 12, 21), settled_through=date(2025, 12, 20), expected_currency='USD', **kwargs)


def test_valid_series_and_universe_budget():
    assert UNIVERSE_TARGET == 1000 and PAGE_SIZE == 20
    result = evaluate(series())
    assert result['status'] == 'ok'
    assert result['current']['status'] == 'forming'
    assert not result['price_verified'] and not result['clear_price_signal']


@pytest.mark.parametrize('change,reason', [
    ({'currency': 'GBp'}, 'currency_mismatch'),
    ({'adjusted_close': None}, 'unverified_adjusted_series'),
    ({'close': 0}, 'unverified_adjusted_series'),
    ({'close': float('nan')}, 'unverified_adjusted_series'),
    ({'source': ''}, 'unverified_adjusted_series'),
])
def test_bad_data_fails_closed(change, reason):
    rows = series(); rows[-1] = replace(rows[-1], **change)
    assert evaluate(rows)['reason'] == reason


def test_conflicting_price_not_a_clear_four_x():
    assert evaluate(series(), reference_close=91.61, reference_date=date(2025, 12, 20))['reason'] == 'conflicting_same_session_price'


def test_reference_must_match_the_session():
    result = evaluate(series(), reference_close=135, reference_date=date(2025, 12, 19))
    assert not result['price_verified']
    assert evaluate(series(), reference_close=135, reference_date=date(2025, 12, 20))['price_verified']


def test_stale_empty_and_duplicates():
    assert evaluate([])['reason'] == 'no_settled_prices'
    assert evaluate(series()[:-1])['reason'] == 'stale'
    assert evaluate(series() + [series()[-1]])['reason'] == 'duplicate_session'


def test_future_rows_cannot_affect_signal():
    rows = series(); extra = RadarPrice(date(2026, 1, 20), 1, 1, 'USD', 'official')
    assert evaluate(rows) == evaluate(rows + [extra])
    assert evaluate_candidate(rows, as_of=date(2025, 12, 1), settled_through=date(2025, 12, 20), expected_currency='USD')['reason'] == 'future_session'


def test_too_young_not_invented():
    assert evaluate(series()[-5:])['reason'] == 'insufficient_history'


def good_quality():
    return dict(sector='Technology', funnel_passed=True, leverage=1.5,
                fcf_current=110, fcf_previous=100, periods_comparable=True,
                fundamentals_age_days=90, median_dollar_volume=10_000_000,
                volume_sessions=20, market_cap_usd=5_000_000_000)


def test_quality_separate_from_price():
    from app.services.propicks_dca_radar import quality_checks
    assert quality_checks(**good_quality())['passed']


@pytest.mark.parametrize('changes,reason', [
    ({'sector': 'Financial Services'}, 'sector_model_required'),
    ({'funnel_passed': False}, 'quality_funnel_not_passed'),
    ({'leverage': None}, 'leverage_missing_or_high'),
    ({'leverage': 3}, 'leverage_missing_or_high'),
    ({'fundamentals_age_days': 151}, 'fundamentals_stale_or_missing'),
    ({'fundamentals_age_days': None}, 'fundamentals_stale_or_missing'),
    ({'periods_comparable': False}, 'fcf_periods_not_comparable'),
    ({'fcf_current': None}, 'fcf_not_positive_and_growing'),
    ({'fcf_previous': -1}, 'fcf_not_positive_and_growing'),
    ({'fcf_current': 90}, 'fcf_not_positive_and_growing'),
    ({'volume_sessions': 19}, 'liquidity_missing_or_low'),
    ({'median_dollar_volume': 4_000_000}, 'liquidity_missing_or_low'),
    ({'market_cap_usd': None}, 'market_cap_missing_or_low'),
])
def test_quality_missing_and_failed_are_not_clear(changes, reason):
    from app.services.propicks_dca_radar import quality_checks
    result = quality_checks(**{**good_quality(), **changes})
    assert not result['passed'] and reason in result['reasons']


def test_stable_twenty_row_pages_and_tracked_exclusion():
    from app.services.propicks_dca_radar import page_candidates
    rows = [{'ticker': f'T{i:03}', 'level': 4} for i in reversed(range(45))]
    first = page_candidates(rows, outside_tracked={'T000'})
    second = page_candidates(rows, page=2, outside_tracked={'T000'})
    assert first['total'] == 44 and len(first['items']) == 20 and first['has_more']
    assert first['items'][0]['ticker'] == 'T001'
    assert not {x['ticker'] for x in first['items']} & {x['ticker'] for x in second['items']}
    assert not page_candidates(rows, page=3)['has_more']
    assert page_candidates(rows, level=3)['total'] == 0
    assert page_candidates(rows, page=0)['page'] == 1


def test_clear_opportunity_needs_both_quality_and_current_confirmed_prices():
    from app.services.propicks_dca_radar import explain_candidate
    price = dict(status='ok', price_verified=True, current={'level': 4, 'status': 'forming'},
                 confirmed={'level': 4, 'status': 'confirmed'})
    assert explain_candidate(price, {'passed': True})['clear_opportunity']
    assert not explain_candidate({**price, 'price_verified': False}, {'passed': True})['clear_opportunity']
    assert not explain_candidate({**price, 'current': {'level': 1}}, {'passed': True})['clear_opportunity']
    assert not explain_candidate({**price, 'confirmed': None}, {'passed': True})['clear_opportunity']
    assert not explain_candidate(price, {'passed': False})['clear_opportunity']
    assert explain_candidate(price, {'passed': False, 'reasons': ['fcf_missing']})['reasons'] == ['fcf_missing']
    assert explain_candidate({'status': 'invalid', 'reason': 'stale'}, {})['reasons'] == ['stale']
    assert explain_candidate({}, {})['reasons'] == ['price_unavailable']


def test_recent_changes_need_comparable_prior_scans_not_month_status():
    from app.services.propicks_dca_radar import signal_change
    current = dict(status='ok', formula_version='nico-v2', price_date='2026-10-29', current={'level': 4})
    previous = {**current, 'price_date': '2026-10-28', 'current': {'level': 3}}
    assert signal_change(current, None) == {'status': 'history_pending', 'changed': None}
    assert signal_change(current, previous)['changed'] is True
    assert signal_change(current, {**previous, 'current': {'level': 4}})['changed'] is False
    assert signal_change(current, current)['status'] == 'not_newer'
    assert signal_change(current, {**previous, 'formula_version': 'nico-v0'})['status'] == 'not_comparable'
    assert signal_change(current, {**previous, 'status': 'invalid'})['changed'] is None
    assert signal_change({**current, 'formula_version': None}, previous)['changed'] is None



def test_staleness_is_measured_against_today_not_self_declared_last_session():
    rows = series()
    result = evaluate_candidate(rows, as_of=date(2026, 1, 2),
                                settled_through=date(2025, 12, 20), expected_currency='USD')
    assert result['reason'] == 'stale'


def test_daily_drawdown_is_context_only_and_does_not_change_formula():
    rows = series()
    rows[-1] = replace(rows[-1], close=120, adjusted_close=120)
    result = evaluate(rows)
    assert result['daily_close_drawdown'] == pytest.approx(1 - 120 / 134)
    assert result['current']['metrics']['signal'] == 'combined'
    assert 'not intraday high' in result['drawdown_basis']
