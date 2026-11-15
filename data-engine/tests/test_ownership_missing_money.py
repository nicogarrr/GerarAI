from datetime import date

import pytest

from app.services.ticker_ownership_signals import insider_signal, ownership_fact_lines, ownership_markdown
from tests.test_ticker_ownership_signals import _db, _filing, _tx


@pytest.mark.parametrize('side', ['P', 'S'])
def test_missing_money_is_not_zero_or_a_net_flow(side):
    db = _db()
    filing = _filing(db, 'UBER', date.today().isoformat())
    _tx(db, filing, insider='Unknown Price', code=side, shares=1000, price=None, tx_date=date.today().isoformat())
    _tx(db, filing, insider='Known Price', code=side, shares=100, price=10, tx_date=date.today().isoformat())
    db.commit()
    result = insider_signal(db, 'UBER')
    target = result['buys' if side == 'P' else 'sells']
    assert target['trades'] == 2
    assert target['value'] is None
    assert target['value_missing'] == 1
    assert result['net_value'] is None
    assert result['reading'] == 'Saldo neto no estimable: faltan importes'
    evidence = {'ticker': 'UBER', 'insider': result, 'holders': {'status': 'sin_datos'}}
    text = ownership_fact_lines(evidence)[0][0]
    assert 'N/D' in text
    assert '1 sin importe' in text
    assert '2 operaciones por N/D' in text
    assert 'N/D' in ownership_markdown(evidence)
    db.close()


@pytest.mark.parametrize('price, expected', [(0, 0), (10, 10000)])
def test_known_zero_and_price_times_shares_remain_known(price, expected):
    db = _db()
    filing = _filing(db, 'UBER', date.today().isoformat())
    _tx(db, filing, insider='Known', code='P', shares=1000, price=price, tx_date=date.today().isoformat())
    db.flush()
    from app.models.entities import InsiderTransaction
    db.query(InsiderTransaction).update({'value': None})
    db.commit()
    result = insider_signal(db, 'UBER')
    assert result['buys']['value'] == expected
    assert result['net_value'] == expected
    assert 'value_missing' not in result['buys']
    db.close()


def test_missing_amount_does_not_erase_cluster_by_count():
    db = _db()
    filing = _filing(db, 'UBER', date.today().isoformat())
    for name in ['One', 'Two', 'Three']:
        _tx(db, filing, insider=name, code='P', shares=10, price=None, tx_date=date.today().isoformat())
    db.commit()
    result = insider_signal(db, 'UBER')
    assert result['cluster_buying'] is True
    assert result['net_value'] is None
    assert result['buys']['value_missing'] == 3
    assert 'Compras en grupo' in result['reading']
    assert 'N/D (3 sin importe)' in ownership_fact_lines({'ticker':'UBER','insider':result})[0][0]
    db.close()


@pytest.mark.parametrize('counter', [None, 0, 1, 3])
def test_missing_counter_is_a_count_not_a_monetary_default(counter):
    from app.services.ticker_ownership_signals import _insider_line

    side = {'insiders': 1, 'trades': 1, 'value': None, 'value_missing': counter}
    line = _insider_line('TEST', {
        'buys': side, 'sells': side, 'window_days': 180,
        'net_value': None, 'reading': 'test',
    })
    assert 'por N/D' in line
    assert 'Saldo neto N/D' in line
    if counter:
        assert f'N/D ({counter} sin importe)' in line
    else:
        assert 'sin importe' not in line
    assert '$0' not in line


@pytest.mark.parametrize('publication', ['2026-11-13', '2026-11-15'])
def test_publication_cutoff_composes_with_incomplete_amounts(publication):
    """Unpublished unknown money cannot taint today's known balance."""
    db = _db()
    as_of = date(2026, 11, 14)
    try:
        known = _filing(db, 'UBER', '2026-11-14')
        _tx(db, known, insider='Known Seller', code='S', shares=100, price=10, tx_date='2026-11-13')
        unknown = _filing(db, 'UBER', publication)
        _tx(db, unknown, insider='Unknown Buyer', code='P', shares=1000, price=None, tx_date='2026-11-13')
        db.commit()
        result = insider_signal(db, 'UBER', as_of=as_of)
        assert result['sells']['value'] == 1000
        text = ownership_fact_lines({'ticker': 'UBER', 'insider': result})[0][0]
        if publication > as_of.isoformat():
            assert result['buys']['trades'] == 0
            assert result['net_value'] == -1000
            assert 'value_missing' not in result['buys']
        else:
            assert result['buys']['trades'] == 1
            assert result['buys']['value'] is None
            assert result['net_value'] is None
            assert 'N/D (1 sin importe)' in text
    finally:
        db.close()
