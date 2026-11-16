"""A known value/vote subtotal with an unknown component is not a complete figure.

Mirror of test_form13f_incomplete_shares: antes un componente ilegible de
value_usd_thousands o de votos se sumaba como 0 en silencio y el agregado
persistido (ManagerHolding.value_usd_thousands) quedaba por debajo del real
con cara de cifra exacta (Lote 1, hallazgo 2 del carril de auditoria).
"""
import pytest

from app.services.connectors.form13f import aggregate_rows


def _row(value='100', sole='50', shares='10'):
    return {'cusip': '037833100', 'title_of_class': 'COM', 'ssh_prnamt': shares,
            'value_usd_thousands': value, 'voting_sole': sole, 'voting_shared': '0',
            'voting_none': '0', 'ssh_prnamt_type': 'SH'}


@pytest.mark.parametrize('bad', [None, '', 'bad', 'NaN', 'Infinity', '-1', 'True'])
@pytest.mark.parametrize('reverse', [False, True])
def test_unknown_component_makes_value_and_votes_unknown(bad, reverse):
    rows = [_row(value='5000', sole='200'), _row(value=bad, sole=bad)]
    if reverse:
        rows.reverse()
    # Una tercera fila valida no debe "completar" el subtotal desconocido.
    rows.append(_row(value='1000', sole='40'))
    result = aggregate_rows(rows)[0]
    assert result['value_usd_thousands'] is None
    assert result['voting_sole'] is None
    # Las acciones siguen sumando con normalidad (componentes validas).
    assert result['ssh_prnamt'] == '30'


def test_valid_components_still_sum_and_reported_zero_is_known():
    result = aggregate_rows([_row(value='0', sole='0'), _row(value='2500.5', sole='100')])[0]
    assert result['value_usd_thousands'] == '2500.5'
    assert result['voting_sole'] == '100'


@pytest.mark.parametrize('bad', [None, '', 'bad', 'NaN', 'Infinity', '-1', 'True'])
def test_single_row_unparseable_value_stays_unknown_not_zero(bad):
    # Fila unica real (sin otra fila que dispare la rama de suma): la entrada
    # ilegible tampoco pasa verbatim al agregado.
    result = aggregate_rows([_row(value=bad, sole=bad)])[0]
    assert result['value_usd_thousands'] is None
    assert result['voting_sole'] is None


def test_single_row_parseable_value_and_votes_pass_through():
    result = aggregate_rows([_row(value='1000.5', sole='42')])[0]
    assert result['value_usd_thousands'] == '1000.5'
    assert result['voting_sole'] == '42'
