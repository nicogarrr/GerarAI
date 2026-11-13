"""Non-finite N-PORT quantities cannot form a complete public holding."""
import pytest

from app.services.connectors import form_nport_dataset as nport
from tests.test_fund_holders import APPLE, _zip


@pytest.mark.parametrize('amount', ['NaN', 'sNaN', 'Infinity', '-Infinity'])
def test_nonfinite_requested_long_shares_reject_dataset(amount):
    row = f'A1\t99\tApple\t\tCOM\t{APPLE}\t{amount}\tNS\t\tUSD\t1\t\t1\tLong'
    with pytest.raises(ValueError, match='N-PORT'):
        nport.parse_dataset(_zip([row]), {APPLE})


def test_unrequested_nonfinite_balance_does_not_change_requested_holdings():
    row = 'A1\t99\tOther\t\tCOM\tOTHER\tInfinity\tNS\t\tUSD\t1\t\t1\tLong'
    assert nport.parse_dataset(_zip([row]), {APPLE})['A1'].shares[APPLE] == 1000
