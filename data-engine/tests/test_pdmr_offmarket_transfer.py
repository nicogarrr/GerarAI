"""Kooth's disclosed internal reorganisation is not an open-market sale.

Observed 2026-11-14 in https://tracefour.com/v1/eu/uk and verified against:
https://data.fca.org.uk/artefacts/NSM/RNS/45d4f9de-5e99-4182-ac11-4802c9fff4b1.html
The notice says all vehicles are managed/controlled by ScaleUp and its total
interest of 9,240,679 ordinary shares (25.4%) is unchanged.
"""
import pytest

from app.services.connectors.uk_pdmr_tracefour import map_entry, map_transaction_code


@pytest.mark.parametrize('nature', [
    'Disposal of ordinary shares by way of off-market transfer',
    'Acquisition of ordinary shares by way of off-market transfer',
    'DISPOSAL BY WAY OF OFF-MARKET TRANSFER',
])
def test_off_market_transfer_is_neutral(nature):
    assert map_transaction_code(nature) is None


@pytest.mark.parametrize('nature,code', [
    ('Sale of Ordinary Shares', 'S'),
    ('Purchase of Ordinary Shares', 'P'),
    ('Disposal of shares', 'S'),
    ('Acquisition of shares', 'P'),
    ('Off-market sale of ordinary shares', 'S'),
    ('Off-market purchase of ordinary shares', 'P'),
])
def test_other_sales_and_purchases_unchanged(nature, code):
    assert map_transaction_code(nature) == code


def test_mapping_preserves_all_other_fields():
    entry = {'filingId': 'example', 'isin': 'GB00EXAMPLE0', 'transactionNature': 'Disposal of ordinary shares by way of off-market transfer', 'volume': 100, 'pricePerShare': 1.35, 'totalValue': 135, 'currency': 'GBP', 'valueUnknown': False}
    mapped = map_entry(entry)
    ordinary = map_entry({**entry, 'transactionNature': 'Disposal of shares'})
    assert ordinary['code'] == 'S'
    assert mapped['code'] is None
    assert {k: v for k, v in mapped.items() if k not in ('code', 'transaction_nature')} == {k: v for k, v in ordinary.items() if k not in ('code', 'transaction_nature')}
