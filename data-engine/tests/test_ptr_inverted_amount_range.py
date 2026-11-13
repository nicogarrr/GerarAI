"""Contradictory declared amount bounds are unknown, not a plausible volume."""
import pytest

from app.services.connectors.house_ptr import parse_amount


@pytest.mark.parametrize('text', ['$50,000 - $15,001', '$5 - $1'])
def test_inverted_bounds_remain_unknown_without_swapping_or_averaging(text):
    parsed = parse_amount(text)
    assert parsed == {'amount_text': text, 'amount_min': None, 'amount_max': None}


def test_equal_bounds_are_a_valid_closed_range():
    assert parse_amount('$5 - $5') == {'amount_text': '$5 - $5', 'amount_min': 5, 'amount_max': 5}
