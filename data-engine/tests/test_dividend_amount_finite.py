"""Nonfinite provider amounts are invalid, never dividend figures."""
from decimal import Decimal

import pytest

from app.services.dividend_ingestion_service import DividendIngestionService


@pytest.mark.parametrize('value', ['Infinity', '-Infinity', 'NaN', 'sNaN', float('inf'), float('nan')])
@pytest.mark.parametrize('field', ['adjDividend', 'dividend', 'amount'])
def test_nonfinite_amounts_are_rejected_without_exception(value, field):
    assert DividendIngestionService._parse_amount({field: value}) is None


@pytest.mark.parametrize('value', ['Infinity', 'NaN', 'sNaN', '-Infinity'])
def test_invalid_adjusted_amount_falls_back_to_valid_provider_amount(value):
    assert DividendIngestionService._parse_amount({'adjDividend': value, 'dividend': '0.25'}) == Decimal('0.25')


@pytest.mark.parametrize('value', ['0', '-1', 'invalid', None])
def test_existing_invalid_amount_behavior_is_preserved(value):
    assert DividendIngestionService._parse_amount({'amount': value}) is None


def test_valid_finite_amount_is_unchanged():
    assert DividendIngestionService._parse_amount({'amount': '1.2345'}) == Decimal('1.2345')
