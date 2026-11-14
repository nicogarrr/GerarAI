"""Los bloques no leídos no desaparecen al agregar la ficha de un político."""
import pytest

from app.services.politician_trades import _member_card


@pytest.mark.parametrize('counts,expected', [([2, 3], 5), ([0, 0], 0), ([None, 2], 2)])
def test_member_card_preserves_unread_blocks_without_inventing_trades(counts, expected):
    records = []
    for count in counts:
        record = {'member': 'Fixture', 'filing_date': '2026-11-01', 'readable': True,
                  'trades': [{'tx_date': '2026-10-01', 'days_late': 0, 'amount_min': 1001, 'amount_max': 15000}]}
        if count is not None:
            record['unparsed_blocks'] = count
        records.append(record)
    card = _member_card('fixture', records)
    assert card['unparsed_blocks'] == expected
    assert card['trades'] == 2  # Los bloques no son un número de operaciones.
    assert card['on_time_pct'] == 100
    assert card['volume_min'] == 2002
