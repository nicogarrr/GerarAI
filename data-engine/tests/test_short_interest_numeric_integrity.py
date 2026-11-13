"""Invalid FINRA counts remain unknown, never truncated or signed positions."""
import pytest

from app.services.connectors.short_interest import parse_short_interest_record


@pytest.mark.parametrize('field,key', [
    ('currentShortPositionQuantity', 'short_interest'),
    ('previousShortPositionQuantity', 'previous_short_interest'),
    ('averageDailyVolumeQuantity', 'average_daily_volume'),
])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, 1.5, True, 'bad', 10**400])
def test_bad_counts_are_unknown_without_crashing(field, key, value):
    record = {'symbolCode': 'EXAMPLE', field: value}
    parsed = parse_short_interest_record(record, 'EXAMPLE')
    assert parsed[key] is None
    assert parsed['change_pct'] is None
    assert parsed['days_to_cover'] is None


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, True])
def test_bad_reported_days_are_unknown(value):
    parsed = parse_short_interest_record({'symbolCode': 'EXAMPLE', 'daysToCoverQuantity': value}, 'EXAMPLE')
    assert parsed['days_to_cover'] is None


def test_real_zero_counts_and_finite_derived_ratios_are_preserved():
    parsed = parse_short_interest_record({'symbolCode': 'EXAMPLE',
        'currentShortPositionQuantity': 0, 'previousShortPositionQuantity': 100,
        'averageDailyVolumeQuantity': 10}, 'EXAMPLE')
    assert parsed['short_interest'] == 0
    assert parsed['days_to_cover'] == 0
    assert parsed['change_pct'] == -1
