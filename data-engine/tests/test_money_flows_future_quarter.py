"""Reported quarterly spending cannot come from a future fiscal period."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models import FinancialFact
from app.services.money_flows import _latest_quarterly_fact, _latest_quarterly_facts_batch, _observed_quarter
from tests.test_money_flows import _seed_capex, db  # noqa: F401


@pytest.mark.parametrize('period', [f'{date.today().year + 1}-03-31:Q1', 'not-a-period'])
def test_future_or_malformed_quarter_does_not_replace_real_spending(db, period):
    company = _seed_capex(db)
    db.add(FinancialFact(company_id=company.id, metric='capital_expenditure',
        value=Decimal('99999999999'), unit='USD', period=period,
        fiscal_quarter='Q1', source_type='SEC', is_reported=True, tenant_id=None))
    db.commit()
    one = _latest_quarterly_fact(db, company.id, 'capital_expenditure', 1)
    batch = _latest_quarterly_facts_batch(db, [company.id], 1)
    assert one.period == '2026-03-31:Q1'
    assert batch[(company.id, 'capital_expenditure')].id == one.id


@pytest.mark.parametrize(('period', 'expected'), [
    (f'{date.today().isoformat()}:Q1', True),
    ('2026-02-30:Q1', False),
    ('2025-12-31:FY', False),
    (None, False),
])
def test_observed_quarter_bounds(period, expected):
    assert _observed_quarter(SimpleNamespace(period=period)) is expected
