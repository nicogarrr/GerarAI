"""Una aportación con fecha futura no se registra (servicio y API)."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base
from app.services.investment_plan_service import InvestmentPlanService
from tests.test_investment_plan_service import _plan


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def test_future_contribution_is_rejected_and_not_counted(db):
    service = InvestmentPlanService()
    _plan(service, db)
    with pytest.raises(ValueError, match="futura"):
        service.add_contribution(db, date_=date.today() + timedelta(days=40), amount=Decimal("500"))
    assert service.list_contributions(db) == []


def test_today_and_tomorrow_are_accepted_for_timezone_slack(db):
    service = InvestmentPlanService()
    _plan(service, db)
    service.add_contribution(db, date_=date.today(), amount=Decimal("100"))
    service.add_contribution(db, date_=date.today() + timedelta(days=1), amount=Decimal("100"))
    assert len(service.list_contributions(db)) == 2
