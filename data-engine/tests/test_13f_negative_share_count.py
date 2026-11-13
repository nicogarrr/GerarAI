"""A negative long-share count must not disappear as a verified absence."""
import pytest

from app.services.connectors.form13f_dataset import parse_dataset
from tests.test_13f_dataset_nonfinite_shares import CUSIP, _dataset


@pytest.mark.parametrize('amount', ['-1', '-1,234', '-0.5'])
def test_negative_requested_shares_reject_dataset(amount):
    with pytest.raises(ValueError, match='13F'):
        parse_dataset(_dataset(amount), {CUSIP})


def test_zero_shares_still_means_no_positive_holding():
    assert parse_dataset(_dataset('0'), {CUSIP}).filings['A'].shares == {}


def test_negative_unrequested_shares_do_not_block_requested_cusip():
    assert parse_dataset(_dataset('-1'), {'000000000'}).filings['A'].shares == {}
