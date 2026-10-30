"""«Este mes» del plan DCA es el de Madrid, no el día UTC del servidor."""
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core import local_date
from app.models.entities import Base, InvestmentPlan, Portfolio
from app.services import plan_contribution_split
from app.services.investment_plan_service import InvestmentPlanService

# 31-mar-2030 22:30 UTC = 1-abr-2030 00:30 en Madrid (CEST).
_INSTANT = datetime(2030, 3, 31, 22, 30, tzinfo=UTC)


def _metrics(today: date | None):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "t"
        db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
        db.add(
            InvestmentPlan(
                monthly_contribution=Decimal("500"),
                monthly_contribution_currency="EUR",
                start_date=date(2030, 1, 1),
                horizon_years=10,
                target_allocations=[],
            )
        )
        db.commit()
        return InvestmentPlanService().plan_metrics(db, today=today)


def test_split_month_is_madrid_month(monkeypatch):
    monkeypatch.setattr(local_date, "_utc_now", lambda: _INSTANT)
    assert plan_contribution_split._today() == date(2030, 4, 1)


def test_plan_metrics_default_today_is_madrid(monkeypatch):
    monkeypatch.setattr(local_date, "_utc_now", lambda: _INSTANT)
    madrid = _metrics(date(2030, 4, 1))
    implicit = _metrics(None)
    assert implicit["months_elapsed"] == madrid["months_elapsed"]
    assert implicit["months_elapsed"] != _metrics(date(2030, 3, 31))["months_elapsed"]
