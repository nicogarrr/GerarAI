"""EIA reported revenue must remain finite after conversion to USD."""
import pytest

from app.services.energy_flows import SECTORS, parse_retail_revenue


def rows(value, total):
    return [{'period': '2020', 'stateid': 'US', 'sectorid': code,
             'revenue-units': 'million dollars', 'revenue': value if code != 'ALL' else total}
            for code in [*SECTORS, 'ALL']]


def test_boolean_sector_revenue_is_not_one_million_dollars():
    with pytest.raises(ValueError):
        parse_retail_revenue(rows(True, 5))


def test_finite_source_number_cannot_overflow_into_infinite_usd():
    with pytest.raises(ValueError):
        parse_retail_revenue(rows(1e303, 5e303))


def test_zero_and_finite_reported_revenues_are_preserved():
    year, sectors, total = parse_retail_revenue(rows(2, 10))
    assert year == '2020' and total == 10_000_000
    assert all(row['amount'] == 2_000_000 for row in sectors)
    _, _, zero = parse_retail_revenue(rows(0, 0))
    assert zero == 0
