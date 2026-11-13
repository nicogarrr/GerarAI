"""A known subtotal is not the value or average price of the whole trade."""
import pytest

from app.services.insider_feed import _group_tranches


@pytest.mark.parametrize('reverse', [False, True])
def test_missing_value_in_one_tranche_keeps_whole_value_and_average_unknown(reverse):
    base = {'accession_number': 'A', 'insider': 'Person', 'type': 'P',
            'form': '4', 'currency': 'USD', 'date': '2026-11-10'}
    rows = [{**base, 'shares': 10, 'value': 100, 'price': 10},
            {**base, 'shares': 10, 'value': None, 'price': None}]
    result = _group_tranches(rows[::-1] if reverse else rows)[0]
    assert result['shares'] == 20
    assert result['value'] is None
    assert result['price'] is None


def test_missing_share_count_cannot_be_used_as_complete_price_denominator():
    base = {'accession_number': 'A', 'insider': 'Person', 'type': 'P',
            'form': '4', 'currency': 'USD', 'date': '2026-11-10'}
    result = _group_tranches([{**base, 'shares': 10, 'value': 100, 'price': 10},
                             {**base, 'shares': None, 'value': 200, 'price': None}])[0]
    assert result['value'] == 300
    assert result['shares'] is None
    assert result['price'] is None
