"""Missing units on minor-unit listings must not be called major-currency prices."""
from decimal import Decimal
from types import SimpleNamespace

from app.services import news_related_tickers as service


def test_london_legacy_row_does_not_invent_pounds_from_unlabelled_quote():
    company = SimpleNamespace(ticker='TSCO.L', currency='GBP')
    assert service._listed(Decimal('255'), None, company) is None
    assert service._session_change(company, (Decimal('255'), None, None), (Decimal('2.50'), None, 'GBP')) is None


def test_major_unit_legacy_and_explicit_pence_are_still_supported():
    us = SimpleNamespace(ticker='ABC', currency='USD')
    uk = SimpleNamespace(ticker='TSCO.L', currency='GBP')
    assert service._listed(Decimal('110'), None, us) == (Decimal('110'), 'USD')
    assert service._listed(Decimal('255'), 'GBp', uk) == (Decimal('2.55'), 'GBP')
