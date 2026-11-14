"""Provider split ratios must survive finite positive storage precision."""
from datetime import date
from decimal import Decimal

import pytest

from app.services.split_ingestion_service import SplitIngestionService as Service


@pytest.mark.parametrize(('numerator', 'denominator'), [
    ('4', 'Infinity'), ('Infinity', '1'), ('NaN', '1'), ('sNaN', '1'),
    ('1', 'NaN'), ('1', '-Infinity'), ('1e-100', '1'), ('1e100', '1'),
    ('0', '1'), ('1', '0'), ('-1', '1'), ('1', '-1'), ('invalid', '1'),
])
def test_invalid_split_ratios_do_not_raise_or_stage_zero(numerator, denominator):
    ratio = Service._parse_ratio({'numerator': numerator, 'denominator': denominator})
    assert ratio is None
    assert not Service._row_is_ingestible({'effective_date': date(2026, 11, 14), 'ratio': ratio})


# Expected values measured against parent 6670fb3 before changing the parser.
@pytest.mark.parametrize(('numerator', 'denominator', 'expected'), [
    ('4', '1', '4.0000000000'), ('1', '10', '0.1000000000'),
    ('5', '3', '1.6666666667'), ('1', '1', '1.0000000000'),
    ('3', '7', '0.4285714286'),
])
def test_valid_ratios_match_parent(numerator, denominator, expected):
    result = Service._parse_ratio({'numerator': numerator, 'denominator': denominator})
    assert result == Decimal(expected)
    assert result is not None and result.is_finite() and result > 0
    assert Service._row_is_ingestible({'effective_date': date(2026, 11, 14), 'ratio': result}) == (result != 1)
