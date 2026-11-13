"""Transactions on different days cannot acquire one another's reported date."""
from app.services.insider_feed import _group_tranches


def _trade(day, value):
    return {'accession_number': 'A', 'insider': 'Person', 'type': 'P', 'form': '4',
            'currency': 'USD', 'date': day, 'shares': 10, 'price': value / 10,
            'value': value, 'rule_10b5_1': False}


def test_same_filing_different_trade_days_remain_separate():
    result = _group_tranches([_trade('2026-11-10', 100), _trade('2026-11-11', 200)])
    assert [(row['date'], row['value'], row['tranches']) for row in result] == [
        ('2026-11-11', 200, 1), ('2026-11-10', 100, 1)]


def test_same_day_price_tranches_still_merge():
    result = _group_tranches([_trade('2026-11-10', 100), _trade('2026-11-10', 200)])
    assert len(result) == 1
    assert result[0]['shares'] == 20
    assert result[0]['value'] == 300
    assert result[0]['price'] == 15
    assert result[0]['tranches'] == 2
