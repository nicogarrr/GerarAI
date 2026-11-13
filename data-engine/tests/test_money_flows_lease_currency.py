"""Lease figures must never be labelled with another currency."""
from types import SimpleNamespace

import pytest

from app.services.money_flows import _spender_payload
from tests.test_money_flows_bordes import CFG, _capex_lease


@pytest.mark.parametrize('lease_unit', ['EUR', 'unknown', '', None])
def test_incomparable_lease_keeps_capex_and_quality_notice(lease_unit):
    capex, lease = _capex_lease('2026-03-31:Q1')
    lease.unit = lease_unit
    result = _spender_payload(CFG, SimpleNamespace(id=1), capex, lease)
    assert result['amount'] == 2000
    assert result['unit'] == 'USD'
    assert result['extra_amount'] is None
    assert result['extra_source'] is None
    assert result['note'] == 'Leases financieros sin importe comparable: moneda distinta o no disponible'


def test_compatible_lease_zero_is_preserved():
    capex, lease = _capex_lease('2026-03-31:Q1')
    lease.value = 0
    result = _spender_payload(CFG, SimpleNamespace(id=1), capex, lease)
    assert result['extra_amount'] == 0
    assert result['note'] is None


@pytest.mark.parametrize('unit', ['unknown', 'UNKNOWN', '', ' '])
def test_equal_missing_currency_does_not_make_lease_comparable(unit):
    capex, lease = _capex_lease('2026-03-31:Q1')
    capex.unit = lease.unit = unit
    result = _spender_payload(CFG, SimpleNamespace(id=1), capex, lease)
    assert result['extra_amount'] is None
    assert result['note']
