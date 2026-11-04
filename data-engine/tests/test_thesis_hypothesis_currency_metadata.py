"""Valuation API currency is metadata, not a displayable ISO string."""
from types import SimpleNamespace

from app.services.thesis_service import ThesisService


def _value(**overrides):
    return {
        'status': 'partial', 'publishable': False,
        'current_price': 400, 'base_value': 700, 'expected_value': 900,
        'margin_of_safety': 1 - 400 / 900,
        'value_currency': 'USD',
        'currency': {'price_currency': 'USD', 'reporting_currency': 'USD', 'status': 'same'},
        **overrides,
    }


def test_hypothesis_keeps_usd_when_api_currency_is_metadata():
    company = SimpleNamespace(name='UnitedHealth', currency='USD')
    text = ThesisService()._hypothesis(company, _value())
    assert '$400.00' in text
    assert '$900.00' in text
    assert 'indicativa' in text
    assert 'price_currency' not in text


def test_hypothesis_uses_listed_value_currency_not_company_reporting_currency():
    company = SimpleNamespace(name='Synthetic listing', currency='CNY')
    text = ThesisService()._hypothesis(company, _value())
    assert '$400.00' in text
    assert '$900.00' in text
    assert 'CNY' not in text


def test_hypothesis_accepts_legacy_currency_string():
    company = SimpleNamespace(name='Synthetic company', currency='USD')
    text = ThesisService()._hypothesis(company, _value(currency='EUR', value_currency=None))
    assert 'EUR' in text


def test_hypothesis_metadata_without_value_currency_uses_price_currency():
    company = SimpleNamespace(name='Synthetic company', currency='CNY')
    text = ThesisService()._hypothesis(company, _value(value_currency=None))
    assert '$400.00' in text and '$900.00' in text
    assert 'CNY' not in text


def test_hypothesis_full_metadata_keeps_unit_not_bare_amount():
    company = SimpleNamespace(name='UnitedHealth', currency='USD')
    valuation = _value(currency={'price_currency': 'USD', 'reporting_currency': 'USD',
                                'status': 'same', 'fx': None, 'fx_date': '2026-11-03'})
    text = ThesisService()._hypothesis(company, valuation)
    assert '$400.00' in text and '$900.00' in text
