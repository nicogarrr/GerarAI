"""A known share subtotal is not a complete aggregated 13F position."""
import pytest

from app.services.connectors.form13f import aggregate_rows


def _row(shares):
    return {'cusip': '037833100', 'title_of_class': 'COM', 'ssh_prnamt': shares,
            'value_usd_thousands': '100', 'voting_sole': '50'}


@pytest.mark.parametrize('missing', [None, '', 'bad', 'NaN', 'Infinity', '-1', 'True'])
@pytest.mark.parametrize('reverse', [False, True])
def test_unknown_component_makes_share_total_unknown(missing, reverse):
    rows = [_row('50'), _row(missing)]
    if reverse:
        rows.reverse()
    # A third valid row must not make the unknown total look complete again.
    rows.append(_row('25'))
    result = aggregate_rows(rows)[0]
    assert result['ssh_prnamt'] is None
    assert result['value_usd_thousands'] == '300'
    assert result['voting_sole'] == '150'


def test_reported_zero_is_known_and_single_unknown_stays_unknown():
    assert aggregate_rows([_row('0'), _row('50')])[0]['ssh_prnamt'] == '50'
    assert aggregate_rows([_row(None)])[0]['ssh_prnamt'] is None
