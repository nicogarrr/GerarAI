"""Invalid closes must not become prices or market moves in news strips."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import news_related_tickers as service


@pytest.mark.parametrize('value', [0, 'NaN', 'Infinity', '-Infinity'])
def test_invalid_raw_price_is_unknown(value):
    company = SimpleNamespace(ticker='ABC', currency='USD')
    assert service._listed(value, 'USD', company) is None
    assert service._listed(value, None, company) is None


@pytest.mark.parametrize('value', [0, 'NaN', 'Infinity'])
def test_invalid_close_cannot_become_a_session_change(value):
    company = SimpleNamespace(ticker='ABC', currency='USD')
    assert service._session_change(company, (Decimal(str(value)), None, 'USD'), (Decimal('100'), None, 'USD')) is None
    assert service._session_change(company, (Decimal('110'), None, 'USD'), (Decimal(str(value)), None, 'USD')) is None


def test_invalid_adjusted_closes_fall_back_to_valid_raw_closes():
    company = SimpleNamespace(ticker='ABC', currency='USD')
    assert service._session_change(company, (Decimal('110'), Decimal('Infinity'), 'USD'),
                                    (Decimal('100'), Decimal('100'), 'USD')) == 10
