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
    assert rows[0].metadata_['resolved_by'] == 'savings-plan'
    assert rows[0].metadata_['resolution_reason'] == 'superseded_plan_state'
    assert rows[0].metadata_['superseded_by_fingerprint'] == rows[1].fingerprint
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
    result = review_savings_plan(db)
    assert result['plan_exists'] is False and result['new_in_app_alerts'] == 0


def test_resolution_preserves_prior_metadata_and_other_tenant(db):
    save(db, currency=None)
    owner_alert = db.scalar(select(ResearchAlert))
    owner_alert.metadata_ = {**owner_alert.metadata_, 'custom': 'keep'}
    db.commit()
    db.info['tenant_id'] = 'other'
    save(db, amount='200')
    other_alert = db.scalar(select(ResearchAlert).where(ResearchAlert.tenant_id == 'other'))
    db.info['tenant_id'] = 'owner'
    save(db, currency='EUR')
    assert owner_alert.metadata_['custom'] == 'keep'
    assert owner_alert.metadata_['resolved_by'] == 'savings-plan'
    assert other_alert.status == 'open'
    assert 'resolved_by' not in other_alert.metadata_


def test_dismissed_notice_keeps_its_resolution_provenance(db):
    save(db)
    dismissed = db.scalar(select(ResearchAlert))
    dismissed.status = 'resolved'
    dismissed.metadata_ = {**dismissed.metadata_, 'resolved_by': 'user'}
    db.commit()
    save(db, amount='200')
    assert dismissed.metadata_['resolved_by'] == 'user'
    assert 'superseded_by_fingerprint' not in dismissed.metadata_
