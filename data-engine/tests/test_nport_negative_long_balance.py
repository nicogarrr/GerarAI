"""A negative long balance is not a verified absence or complete subtotal."""
import pytest

from app.services.connectors import form_nport_dataset as nport
from tests.test_fund_holders import APPLE, _zip


@pytest.mark.parametrize('amount', ['-1', '-1,234', '-0.5'])
def test_negative_requested_long_balance_rejects_dataset(amount):
    row = f'A1\t99\tApple\t\tCOM\t{APPLE}\t{amount}\tNS\t\tUSD\t1\t\t1\tLong'
    with pytest.raises(ValueError, match='N-PORT'):
        nport.parse_dataset(_zip([row]), {APPLE})


@pytest.mark.parametrize('amount,cusip,profile', [('0', APPLE, 'Long'),
    ('-1', 'OTHER', 'Long'), ('-1', APPLE, 'Short')])
def test_zero_unrequested_and_short_keep_prior_semantics(amount, cusip, profile):
    row = f'A1\t99\tApple\t\tCOM\t{cusip}\t{amount}\tNS\t\tUSD\t1\t\t1\t{profile}'
    assert nport.parse_dataset(_zip([row]), {APPLE})['A1'].shares[APPLE] == 1000
