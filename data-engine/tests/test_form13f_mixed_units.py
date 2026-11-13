"""Keep USD values but never sum shares and principal as one quantity."""
import pytest

from app.services.connectors.form13f import aggregate_rows


def row(unit, amount='10'):
    return {'cusip': '037833100', 'title_of_class': 'COM', 'ssh_prnamt': amount,
            'ssh_prnamt_type': unit, 'value_usd_thousands': '100'}


@pytest.mark.parametrize('units', [('SH', 'PRN'), ('PRN', 'SH'), ('SH', None), ('SH', 'bad')])
def test_mixed_or_missing_units_do_not_create_a_quantity_total(units):
    result = aggregate_rows([row(units[0]), row(units[1]), row('SH')])[0]
    assert result['ssh_prnamt'] is None
    assert result['ssh_prnamt_type'] == 'MIXED'
    assert result['value_usd_thousands'] == '300'


@pytest.mark.parametrize('unit', ['SH', 'PRN'])
def test_known_identical_units_still_sum(unit):
    result = aggregate_rows([row(unit), row(unit, '20')])[0]
    assert result['ssh_prnamt'] == '30'
    assert result['ssh_prnamt_type'] == unit


def test_single_unknown_unit_cannot_claim_a_known_quantity():
    result = aggregate_rows([row(None)])[0]
    assert result['ssh_prnamt'] is None
    assert result['ssh_prnamt_type'] == 'UNKNOWN'
