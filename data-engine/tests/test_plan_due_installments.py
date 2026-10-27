"""La cuota del mes en curso no cuenta como exigible hasta su aniversario."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, InvestmentPlan, Portfolio
from app.services.investment_plan_service import InvestmentPlanService


def _metrics(today: date, start: date = date(2026, 1, 15)):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "t"
        db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
        db.add(
            InvestmentPlan(
                monthly_contribution=Decimal("500"),
                monthly_contribution_currency="EUR",
                start_date=start,
                horizon_years=10,
                target_allocations=[],
            )
        )
        db.commit()
        return InvestmentPlanService().plan_metrics(db, today=today)


@pytest.mark.parametrize(
    ("today", "due"),
    [
        (date(2026, 10, 10), 8),  # 15-oct aun no vence
        (date(2026, 10, 15), 9),  # el dia del aniversario ya vence
        (date(2026, 10, 20), 9),
        (date(2026, 1, 20), 0),
        (date(2026, 2, 14), 0),
        (date(2026, 2, 15), 1),
    ],
)
def test_expected_counts_only_due_anniversaries(today, due):
    m = _metrics(today)
    assert m["expected_contributions_base"] == 500.0 * due


def test_user_up_to_date_is_on_track_before_anniversary():
    # 8 cuotas aportadas = al corriente el 10-oct (antes fallaba con gap 500).
    m = _metrics(date(2026, 10, 10))
    assert m["months_elapsed"] == 9
    assert m["expected_contributions_base"] == 4000.0
