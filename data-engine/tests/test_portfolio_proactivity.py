from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.models import (
    CashBalance,
    Company,
    InvestmentPlan,
    PortfolioDailySnapshot,
    PositionDailySnapshot,
    ResearchAlert,
)
from app.models.entities import Base
from app.services.portfolio_proactivity import review_portfolio_data


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.info['tenant_id'] = 1
        yield db
    engine.dispose()


def setup_snapshot(db, *, targets=None, coverage='1', cash='0', dated=None):
    dated = dated or local_today()
    company = Company(valuation_model='dcf', company_type='public', ticker='ASTS', name='AST', exchange='NASDAQ', currency='USD')
    db.add(company); db.flush()
    plan = InvestmentPlan(tenant_id=1, portfolio_id=1, monthly_contribution=1000,
        start_date=dated, horizon_years=20, target_allocations=targets or [], status='active')
    snapshot = PortfolioDailySnapshot(tenant_id=1, portfolio_id=1, snapshot_date=dated,
        base_currency='EUR', positions_value_base=1000, cash_value_base=Decimal(cash),
        total_value_base=1000+Decimal(cash), pricing_coverage=Decimal(coverage))
    db.add_all([plan,snapshot]); db.flush()
    row = PositionDailySnapshot(tenant_id=1, portfolio_id=1, portfolio_snapshot_id=snapshot.id,
        company_id=company.id, snapshot_date=dated, quantity=1, market_price_native=1000,
        currency='USD', market_value_native=1000, market_value_base=1000)
    db.add(row); db.commit()
    return plan, snapshot, row


def alerts(db): return db.scalars(select(ResearchAlert)).all()


def test_negative_cash_is_dated_not_debt_or_live_and_in_app_only(db):
    db.add(CashBalance(tenant_id=1, currency='EUR', balance=-100, source='ibkr', as_of=date(2026,1,1)))
    db.commit()
    assert review_portfolio_data(db)['new_in_app_alerts'] == 1
    alert = alerts(db)[0]
    assert alert.channels == ['in_app']
    assert alert.metadata_['current_balance_verified'] is False
    assert alert.metadata_['debt_confirmed'] is False
    assert alert.metadata_['orders_enabled'] is False
    assert '2026-01-01' in alert.message
    assert review_portfolio_data(db)['new_in_app_alerts'] == 0
    alert.status = 'resolved'; db.commit()
    assert review_portfolio_data(db)['new_in_app_alerts'] == 0
    assert alert.status == 'resolved'


def test_positive_cash_no_notice_and_other_tenant_private(db):
    db.add(CashBalance(tenant_id=1,currency='EUR',balance=1)); db.commit()
    db.info['tenant_id'] = 2
    db.add(CashBalance(tenant_id=2,currency='EUR',balance=-200)); db.commit()
    db.info['tenant_id'] = 1
    assert review_portfolio_data(db)['new_in_app_alerts'] == 0
    assert not alerts(db)


def test_no_invented_band_even_for_100_percent_position(db):
    setup_snapshot(db, targets=[{'kind':'ticker','label':'ASTS','target_pct':20}])
    assert review_portfolio_data(db)['concentration_status'] == 'no_explicit_ticker_band'
    assert not alerts(db)


def test_explicit_band_uses_net_nav_with_cash_not_gross_and_is_dated(db):
    setup_snapshot(db, targets=[{'kind':'ticker','label':'ASTS','target_pct':40,'band_pct':5}], cash='1000')
    assert review_portfolio_data(db)['new_in_app_alerts'] == 1
    alert = alerts(db)[0]
    assert alert.metadata_['weight_pct'] == '50.0'
    assert alert.metadata_['weight_basis'] == 'nav_with_cash'
    assert alert.metadata_['snapshot_is_live'] is False
    assert alert.channels == ['in_app']
    assert 'no es una orden' in alert.message
    assert review_portfolio_data(db)['new_in_app_alerts'] == 0
    alert.status = 'resolved'; db.commit()
    assert review_portfolio_data(db)['new_in_app_alerts'] == 0


@pytest.mark.parametrize('coverage,cash', [('0.9','0'),('1','-1000'),('1','-1100')])
def test_incomplete_or_nonpositive_nav_cannot_warn_concentration(db,coverage,cash):
    setup_snapshot(db,targets=[{'kind':'ticker','label':'ASTS','target_pct':20,'band_pct':5}],coverage=coverage,cash=cash)
    assert review_portfolio_data(db)['new_in_app_alerts'] == 0


def test_within_band_no_notice(db):
    setup_snapshot(db,targets=[{'kind':'ticker','label':'ASTS','target_pct':50,'band_pct':5}],cash='1000')
    assert review_portfolio_data(db)['new_in_app_alerts'] == 0


def test_cross_tenant_snapshot_not_used(db):
    _, snapshot, row = setup_snapshot(db,targets=[{'kind':'ticker','label':'ASTS','target_pct':20,'band_pct':5}])
    # Another tenant has no access to the owner's plan or snapshot.
    db.info['tenant_id'] = 2
    assert review_portfolio_data(db)['new_in_app_alerts'] == 0


def test_future_snapshot_not_used(db):
    setup_snapshot(db,targets=[{'kind':'ticker','label':'ASTS','target_pct':20,'band_pct':5}],dated=local_today()+timedelta(days=1))
    assert review_portfolio_data(db)['new_in_app_alerts'] == 0
