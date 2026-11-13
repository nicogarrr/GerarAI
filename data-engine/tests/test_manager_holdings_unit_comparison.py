"""13F shares and principal amounts are not interchangeable units."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.manager_holding_ingestion_service import share_change_label


def holding(shares, unit):
    return SimpleNamespace(shares=Decimal(shares), share_type=unit,
                           value_usd_thousands=None, report_date=None)


@pytest.mark.parametrize('now,before', [('SH', 'PRN'), ('PRN', 'SH'),
    ('OTHER', 'OTHER'), ('', 'SH'), (None, 'SH'), ('SH', None)])
def test_incompatible_or_missing_units_are_unknown(now, before):
    assert share_change_label(holding(20, now), holding(10, before)) == 'unknown'


@pytest.mark.parametrize('now,before', [('SH', 'SH'), ('PRN', 'PRN'), (' sh ', 'SH')])
def test_same_known_units_can_be_compared(now, before):
    assert share_change_label(holding(20, now), holding(10, before)) == 'increased'
    assert share_change_label(holding(10, now), holding(20, before)) == 'decreased'
    assert share_change_label(holding(10, now), holding(10, before)) == 'unchanged'
