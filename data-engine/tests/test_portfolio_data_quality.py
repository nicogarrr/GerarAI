from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import CashBalance, Company, Portfolio, PortfolioDailySnapshot, Position, Tenant
from app.services.portfolio_quality_service import portfolio_quality


def test_no_portfolio_is_not_a_zero_measured_return():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        assert portfolio_quality(db)['status'] == 'no_portfolio'


def test_real_failure_shape_is_diagnosed_without_writing_or_inventing_cost():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id='quality-one', name='QA')
        other = Tenant(external_id='quality-other', name='Other')
        db.add_all([tenant, other]); db.flush()
        db.info['tenant_id'] = tenant.id
        p = Portfolio(name='Main', base_currency='EUR', is_default=True)
        c = Company(ticker='QA', name='QA', exchange='X', currency='USD', sector='S', industry='I', company_type='holding', valuation_model='unassigned')
        db.add_all([p, c]); db.flush()
        position = Position(portfolio_id=p.id, company_id=c.id, quantity=10, average_cost=0,
                            cost_basis_base=0, currency='USD', as_of=date(2026, 10, 16), source='ibkr_flex')
        cash = CashBalance(currency='USD', balance=Decimal('-20584.72'), as_of=date(2026, 10, 15), source='ibkr_flex')
        db.add_all([position, cash])
        for day, value, coverage in [(15, 7928, 1), (16, 16996, .8), (17, 0, 0)]:
            db.add(PortfolioDailySnapshot(portfolio_id=p.id, snapshot_date=date(2026, 10, day),
                   base_currency='EUR', positions_value_base=value, cash_value_base=0,
                   total_value_base=value, pricing_coverage=Decimal(str(coverage))))
        db.commit()
        result = portfolio_quality(db)
        assert result['status'] == 'incomplete'
        assert result['missing_cost_positions'] == 1
        assert result['cash_native'] == {'USD': -20584.72}
        assert result['snapshots'] == 3 and result['complete_snapshots'] == 1
        assert result['return_observations'] == 0
        assert set(result['reasons']) == {'missing_cost_basis', 'mixed_valuation_dates', 'latest_snapshot_incomplete', 'insufficient_verified_returns', 'ibkr_cost_currency_unverified'}
        assert not db.new and not db.dirty and not db.deleted
        assert position.average_cost == 0 and cash.balance == Decimal('-20584.72')


def test_quality_is_tenant_scoped_and_does_not_leak_other_cash():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        a = Tenant(external_id='quality-a', name='A')
        b = Tenant(external_id='quality-b', name='B')
        db.add_all([a, b]); db.flush()
        db.add_all([Portfolio(tenant_id=a.id, name='Main', is_default=True, base_currency='EUR'),
                    Portfolio(tenant_id=b.id, name='Main', is_default=True, base_currency='USD'),
                    CashBalance(tenant_id=a.id, currency='EUR', balance=1, as_of=date(2026, 10, 16)),
                    CashBalance(tenant_id=b.id, currency='USD', balance=999999, as_of=date(2026, 10, 16))])
        db.commit()
        db.info['tenant_id'] = a.id
        assert portfolio_quality(db)['cash_native'] == {'EUR': 1.0}
