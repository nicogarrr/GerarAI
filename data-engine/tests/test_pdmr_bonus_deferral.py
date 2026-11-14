"""Required bonus deferrals are not discretionary open-market buy signals.

Observed in https://tracefour.com/v1/eu/uk, verified 2026-11-14 against:
https://data.fca.org.uk/artefacts/NSM/RNS/922684a9-b784-487f-a650-61241dab4444.html
Bellway says its remuneration policy requires directors to defer 25% of
annual bonus into shares held for three years.
"""
import pytest

from app.services.connectors.uk_pdmr_tracefour import map_entry, map_transaction_code


@pytest.mark.parametrize('nature', [
    'Purchase of shares / bonus deferral of 25% of annual bonus',
    'Purchase of shares / bonus deferral of 25% of annual bonus.',
    'PURCHASE OF SHARES / BONUS DEFERRAL OF 25% OF ANNUAL BONUS',
])
def test_bonus_deferral_is_neutral(nature):
    assert map_transaction_code(nature) is None


@pytest.mark.parametrize('nature,code', [
    ('Purchase of Ordinary Shares', 'P'),
    ('Acquisition of shares', 'P'),
    ('On-market purchase', 'P'),
    ('Sale of shares', 'S'),
])
def test_other_transactions_preserved(nature, code):
    assert map_transaction_code(nature) == code


def test_mapping_keeps_reported_amount_shares_and_other_fields():
    entry = {'filingId': '922684a9-b784-487f-a650-61241dab4444|1', 'isin': 'GB0000904986', 'transactionNature': 'Purchase of shares / bonus deferral of 25% of annual bonus', 'volume': 5658, 'pricePerShare': 21.64, 'totalValue': 122439.12, 'currency': 'GBP', 'valueUnknown': False}
    mapped = map_entry(entry)
    ordinary = map_entry({**entry, 'transactionNature': 'Purchase of shares'})
    assert mapped['code'] is None
    assert ordinary['code'] == 'P'
    assert {k: v for k, v in mapped.items() if k not in ('code', 'transaction_nature')} == {k: v for k, v in ordinary.items() if k not in ('code', 'transaction_nature')}
