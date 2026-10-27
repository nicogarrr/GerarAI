"""Escala del ahorro por ejercicio: antes de 2021 no hay tramo del 26 %."""

from decimal import Decimal

from app.services.tax_irpf_filing import calculate_savings_tax, savings_bands


def test_2016_2020_scale_has_no_26_percent_bracket():
    for year in range(2016, 2021):
        assert [b[2] for b in savings_bands(year)] == [Decimal("0.19"), Decimal("0.21"), Decimal("0.23")]
    # 300.000 EUR en 2019: 6.000*19% + 44.000*21% + 250.000*23%
    assert calculate_savings_tax(Decimal("300000"), 2019) == Decimal("67880.00")
    assert calculate_savings_tax(Decimal("300000"), 2021) == Decimal("70880.00")


def test_older_scales():
    assert calculate_savings_tax(Decimal("60000"), 2015) == Decimal("12980.00")
    assert calculate_savings_tax(Decimal("30000"), 2013) == Decimal("7380.00")
    assert calculate_savings_tax(Decimal("10000"), 2011) == Decimal("1980.00")
    assert calculate_savings_tax(Decimal("10000"), 2008) == Decimal("1800.00")


def test_recent_years_unchanged():
    assert calculate_savings_tax(Decimal("400000"), 2024) == Decimal("99880.00")
    assert calculate_savings_tax(Decimal("400000"), 2025) == Decimal("101880.00")
