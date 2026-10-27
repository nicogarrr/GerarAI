"""Regresión: la escala del ahorro es fail-closed fuera de 2007+.

Antes del fix, ``calculate_savings_tax(1000, 1990)`` aplicaba en silencio el
18 % de 2007-2009: una escala no verificada publicada como dato.
"""
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.tax_irpf_filing import calculate_savings_tax, savings_bands


@given(
    income=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000"), places=2),
    year=st.integers(-3000, 2006),
)
@settings(max_examples=60, deadline=None)
def test_unverified_year_raises(income, year):
    with pytest.raises(ValueError, match="no verificada"):
        calculate_savings_tax(income, year)


def test_savings_bands_raises_before_2007():
    with pytest.raises(ValueError, match="no verificada"):
        savings_bands(2006)


def test_verified_years_still_compute():
    assert calculate_savings_tax(Decimal("10000"), 2025) == Decimal("1980")
    assert calculate_savings_tax(Decimal("10000"), 2007) == Decimal("1800")
