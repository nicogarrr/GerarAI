from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import ResearchAlert
from app.models.entities import Base
from app.services.investment_plan_service import InvestmentPlanService
from app.services.plan_proactivity import review_savings_plan

@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info['tenant_id'] = 'owner'
        yield session
    engine.dispose()


def save(db, amount='1000', currency='EUR'):
    return InvestmentPlanService().upsert_plan(db, monthly_contribution=Decimal(amount),
        monthly_contribution_currency=currency, start_date=date(2026, 1, 1), horizon_years=20,
        target_allocations=[])


def test_actual_plan_changes_emit_in_app_only_with_sources(db):
    save(db)
    alerts = db.scalars(select(ResearchAlert)).all()
    assert len(alerts) == 1
    assert alerts[0].channels == ['in_app']
    assert alerts[0].metadata_['projection_url'] == '/portfolio?tab=prevision'
    assert alerts[0].metadata_['orders_enabled'] is False
    save(db)
    assert len(db.scalars(select(ResearchAlert)).all()) == 1
    save(db, amount='500')
    rows = db.scalars(select(ResearchAlert).order_by(ResearchAlert.id)).all()
    assert len(rows) == 2
    assert rows[0].status == 'resolved' and rows[0].resolved_at is not None
    assert rows[1].status == 'open'
    assert sum(a.status == 'open' for a in rows) == 1


def test_resolved_state_does_not_reopen_and_daily_review_dedupes(db):
    save(db, currency=None)
    alert = db.scalar(select(ResearchAlert))
    assert alert.metadata_['reason'] == 'currency_missing'
    assert 'ni asumimos euros' in alert.message
    alert.status = 'resolved'
    db.commit()
    assert review_savings_plan(db)['new_in_app_alerts'] == 0
    save(db, currency=None)
    assert alert.status == 'resolved'
    assert len(db.scalars(select(ResearchAlert)).all()) == 1


def test_other_tenant_does_not_read_plan_or_alerts(db):
    save(db)
    db.info['tenant_id'] = 'other'
    assert review_savings_plan(db) == {'plan_exists': False, 'new_in_app_alerts': 0}
