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
        assert set(result['reasons']) == {'missing_cost_basis', 'mixed_valuation_dates', 'latest_snapshot_incomplete', 'insufficient_verified_returns', 'ibkr_cost_currency_unverified', 'twr_chain_broken'}
        assert result['twr_chain']['status'] == 'broken'
        assert result['twr_chain']['unlinked_snapshots'] == 2
        assert result['twr_chain']['first_unlinked_date'] == '2026-10-16'
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


def test_linked_twr_chain_reports_no_break():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id='quality-linked', name='QA')
        db.add(tenant); db.flush()
        db.info['tenant_id'] = tenant.id
        p = Portfolio(name='Main', base_currency='EUR', is_default=True)
        c = Company(ticker='QL', name='QL', exchange='X', currency='EUR', sector='S', industry='I', company_type='holding', valuation_model='unassigned')
        db.add_all([p, c]); db.flush()
        db.add(Position(portfolio_id=p.id, company_id=c.id, quantity=10, average_cost=100,
                        cost_basis_base=1000, currency='EUR', as_of=date(2026, 10, 16), source='ibkr_flex'))
        # Base (sin retorno por definición) + dos eslabones enlazados.
        db.add(PortfolioDailySnapshot(portfolio_id=p.id, snapshot_date=date(2026, 10, 15),
               base_currency='EUR', positions_value_base=1000, cash_value_base=0,
               total_value_base=1000, pricing_coverage=Decimal('1')))
        for day, ret, twr in [(16, '0.01', '0.01'), (17, '0.01', '0.0201')]:
            db.add(PortfolioDailySnapshot(portfolio_id=p.id, snapshot_date=date(2026, 10, day),
                   base_currency='EUR', positions_value_base=1000, cash_value_base=0,
                   total_value_base=1000, pricing_coverage=Decimal('1'),
                   daily_return=Decimal(ret), cumulative_twr=Decimal(twr)))
        db.commit()
        result = portfolio_quality(db)
        assert result['twr_chain'] == {'status': 'linked', 'unlinked_snapshots': 0, 'first_unlinked_date': None}
        assert 'twr_chain_broken' not in result['reasons']
        assert result['return_observations'] == 2


def test_twr_chain_break_keeps_first_date_after_base():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id='quality-broken', name='QA')
        db.add(tenant); db.flush()
        db.info['tenant_id'] = tenant.id
        p = Portfolio(name='Main', base_currency='EUR', is_default=True)
        c = Company(ticker='QB', name='QB', exchange='X', currency='EUR', sector='S', industry='I', company_type='holding', valuation_model='unassigned')
        db.add_all([p, c]); db.flush()
        db.add(Position(portfolio_id=p.id, company_id=c.id, quantity=10, average_cost=100,
                        cost_basis_base=1000, currency='EUR', as_of=date(2026, 10, 16), source='ibkr_flex'))
        db.add(PortfolioDailySnapshot(portfolio_id=p.id, snapshot_date=date(2026, 10, 14),
               base_currency='EUR', positions_value_base=1000, cash_value_base=0,
               total_value_base=1000, pricing_coverage=Decimal('1')))
        db.add(PortfolioDailySnapshot(portfolio_id=p.id, snapshot_date=date(2026, 10, 15),
               base_currency='EUR', positions_value_base=1000, cash_value_base=0,
               total_value_base=1000, pricing_coverage=Decimal('1'),
               daily_return=Decimal('0.01'), cumulative_twr=Decimal('0.01')))
        # Eslabón roto a mitad de serie (cobertura incompleta -> sin retorno).
        db.add(PortfolioDailySnapshot(portfolio_id=p.id, snapshot_date=date(2026, 10, 16),
               base_currency='EUR', positions_value_base=1000, cash_value_base=0,
               total_value_base=1000, pricing_coverage=Decimal('0.5')))
        db.commit()
        result = portfolio_quality(db)
        assert result['twr_chain']['status'] == 'broken'
        assert result['twr_chain']['first_unlinked_date'] == '2026-10-16'
        assert 'twr_chain_broken' in result['reasons']


def test_scope_change_base_is_not_a_broken_link():
    """#2890 declara base nueva la primera foto real tras una serie
    reconstruida solo-posiciones (twr_base_after_scope_change): sin retorno
    por diseño, no es un eslabón roto. Antes el diagnóstico la contaba como
    rota y pedía otra reconstrucción."""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id='quality-scope-base', name='QA')
        db.add(tenant); db.flush()
        db.info['tenant_id'] = tenant.id
        p = Portfolio(name='Main', base_currency='EUR', is_default=True)
        c = Company(ticker='QS', name='QS', exchange='X', currency='EUR', sector='S', industry='I', company_type='holding', valuation_model='unassigned')
        db.add_all([p, c]); db.flush()
        db.add(Position(portfolio_id=p.id, company_id=c.id, quantity=10, average_cost=100,
                        cost_basis_base=1000, currency='EUR', as_of=date(2026, 10, 18), source='ibkr_flex'))
        # Serie reconstruida solo-posiciones: base + un eslabón.
        db.add(PortfolioDailySnapshot(portfolio_id=p.id, snapshot_date=date(2026, 10, 15),
               base_currency='EUR', positions_value_base=1000, cash_value_base=0,
               total_value_base=1000, pricing_coverage=Decimal('1'),
               source='twr_rebuild', metadata_={'positions_only': True}))
        db.add(PortfolioDailySnapshot(portfolio_id=p.id, snapshot_date=date(2026, 10, 16),
               base_currency='EUR', positions_value_base=1010, cash_value_base=0,
               total_value_base=1010, pricing_coverage=Decimal('1'),
               daily_return=Decimal('0.01'), cumulative_twr=Decimal('0.01'),
               source='twr_rebuild', metadata_={'positions_only': True}))
        # Primera foto real tras el cambio de alcance: base nueva declarada.
        db.add(PortfolioDailySnapshot(portfolio_id=p.id, snapshot_date=date(2026, 10, 17),
               base_currency='EUR', positions_value_base=1010, cash_value_base=0,
               total_value_base=1010, pricing_coverage=Decimal('1'),
               metadata_={'twr_blocked_by_scope_change': True, 'twr_base_after_scope_change': True}))
        db.add(PortfolioDailySnapshot(portfolio_id=p.id, snapshot_date=date(2026, 10, 18),
               base_currency='EUR', positions_value_base=1020, cash_value_base=0,
               total_value_base=1020, pricing_coverage=Decimal('1'),
               daily_return=Decimal('0.0099'), cumulative_twr=Decimal('0.0099')))
        db.commit()
        result = portfolio_quality(db)
        assert result['twr_chain'] == {'status': 'linked', 'unlinked_snapshots': 0, 'first_unlinked_date': None}
        assert 'twr_chain_broken' not in result['reasons']
