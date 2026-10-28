from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base
from app.services.investment_plan_service import InvestmentPlanService
from app.services.savings_projection import project_savings, savings_contract


def test_zero_return_and_effective_monthly_compounding():
    zero = project_savings(monthly=1000, years=20, annual_return=0)
    assert zero['terminal_value'] == zero['contributed'] == 240000
    result = project_savings(monthly=1000, years=20, annual_return=.05)
    assert result['terminal_value'] == 405804.49
    assert result['terminal_annual_gross_dividend'] == 12174.13
    assert result['terminal_monthly_gross_dividend_equivalent'] == 1014.51
    assert result['net_dividend'] is None
    assert result['terminal_value_today_money'] < result['terminal_value']


def test_dividend_not_counted_twice_and_losses_are_possible():
    a = project_savings(monthly=1000, years=20, annual_return=.05, dividend_yield=0)
    b = project_savings(monthly=1000, years=20, annual_return=.05, dividend_yield=.1)
    assert a['terminal_value'] == b['terminal_value']
    loss = project_savings(monthly=1000, years=20, annual_return=-.1)
    assert loss['terminal_value'] < loss['contributed']
    assert project_savings(monthly=0, years=1, annual_return=.05)['terminal_value'] == 0


@pytest.mark.parametrize('change', [dict(monthly=float('nan')), dict(annual_return=float('inf')),
    dict(annual_return=-1), dict(years=2.5), dict(years=True), dict(monthly=-1), dict(dividend_yield=-.1)])
def test_invalid_inputs(change):
    args = dict(monthly=1000, years=20, annual_return=.05)
    args.update(change)
    with pytest.raises(ValueError):
        project_savings(**args)


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info['tenant_id'] = 'savings-owner'
        yield session
    engine.dispose()


def test_plan_contract_preview_and_tenant_isolation(db):
    assert savings_contract(db)['status'] == 'no_plan'
    service = InvestmentPlanService()
    service.upsert_plan(db, monthly_contribution=Decimal('1000'),
        monthly_contribution_currency='USD', start_date=date(2026, 1, 1),
        horizon_years=20, target_allocations=[])
    result = savings_contract(db)
    assert result['currency'] == 'USD'
    assert len(result['scenarios']) == 4
    assert result['scenarios'][2]['terminal_value'] == 405804.49
    assert result['portfolio_included'] is False
    assert result['preview'] is False
    assert savings_contract(db, monthly=500)['status'] == 'currency_missing'
    preview = savings_contract(db, monthly=500, years=10, currency='EUR')
    assert preview['preview'] and preview['currency'] == 'EUR'
    assert savings_contract(db)['monthly_contribution'] == 1000
    db.info['tenant_id'] = 'another-owner'
    assert savings_contract(db)['status'] == 'no_plan'


def test_currency_missing_never_assumed_eur(db):
    InvestmentPlanService().upsert_plan(db, monthly_contribution=Decimal('1000'),
        start_date=date(2026, 1, 1), horizon_years=20, target_allocations=[])
    result = savings_contract(db)
    assert result['status'] == 'currency_missing'
    assert result['currency'] is None and result['scenarios'] == []
