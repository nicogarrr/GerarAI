"""Malformed requested quantities must not become verified absence."""
import pytest

from app.services.connectors.form13f_dataset import parse_dataset
from tests.test_13f_dataset_nonfinite_shares import CUSIP, _dataset


@pytest.mark.parametrize('amount', ['', '--', 'N/A', 'not-a-number'])
def test_unreadable_requested_quantity_rejects_dataset(amount):
    with pytest.raises(ValueError, match='13F'):
        parse_dataset(_dataset(amount), {CUSIP})


def test_unrelated_unreadable_quantity_does_not_block_requested_cusip():
    parsed = parse_dataset(_dataset('N/A'), {'000000000'})
    assert parsed.filings['A'].shares == {}
