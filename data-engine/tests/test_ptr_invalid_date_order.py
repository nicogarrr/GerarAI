"""A transaction after its filing is not evidence of on-time disclosure."""
import pytest

from app.services.connectors.house_ptr import days_late
from app.services.politician_trades import build_record


@pytest.mark.parametrize('transaction,filed', [
    ('2026-10-21', '2026-10-20'),
    ('invalid', '2026-10-20'),
    ('2026-10-20', 'invalid'),
])
def test_impossible_or_invalid_chronology_is_unknown(transaction, filed):
    assert days_late(transaction, filed) is None


def test_record_does_not_certify_impossible_chronology_as_on_time():
    rec = build_record({'doc_id': '20000001', 'filing_date': '2026-10-20'},
        {'trades': [{'tx_date': '2026-10-21'}]}, None)
    assert rec['trades'][0]['days_late'] is None
