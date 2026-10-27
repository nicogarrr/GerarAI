"""Annual exports cannot paginate all-time contributions before filtering year."""
import asyncio
import csv
import io
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.export import export_year
from app.core.database import Base
from app.models import PlanContribution, TaxReport
from app.services.investment_plan_service import InvestmentPlanService


def body(response):
    async def collect():
        return b"".join([x if isinstance(x, bytes) else x.encode() async for x in response.body_iterator])
    return asyncio.run(collect()).decode("utf-8-sig")


def test_export_filters_year_before_any_ui_pagination_and_keeps_all_rows():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        plan = InvestmentPlanService().upsert_plan(db, monthly_contribution=Decimal("1"), start_date=date(2020, 1, 1), horizon_years=30, target_allocations=[])
        db.add_all([PlanContribution(plan_id=plan.id, date=date(2020, 1, 1), amount=Decimal("1"), currency="EUR", external_id=f"old-{i}") for i in range(500)])
        # Over the UI's page limit within the requested year too.
        db.add_all([PlanContribution(plan_id=plan.id, date=date(2026, 10, 27), amount=Decimal("2"), currency="EUR", external_id=f"current-{i}") for i in range(501)])
        db.add(PlanContribution(plan_id=plan.id, date=date(2027, 1, 1), amount=Decimal("999"), currency="EUR", note="future"))
        db.add(TaxReport(fiscal_year=2026, summary={}, dividends=[], realized=[], misc={}))
        db.commit()
        result = json.loads(body(export_year(2026, format="json", db=db)))
        rows = result["plan_contributions"]
        assert len(rows) == 501
        assert sum(r["amount"] for r in rows) == 1002
        assert {r["date"] for r in rows} == {"2026-10-27"}
        csv_rows = list(csv.reader(io.StringIO(body(export_year(2026, format="csv", db=db)))))
        exported = [r for r in csv_rows[1:] if r[0] == "contribution"]
        assert len(exported) == 501
        assert sum(Decimal(r[3]) for r in exported) == 1002


def test_export_without_plan_has_no_contributions():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(TaxReport(fiscal_year=2026, summary={}, dividends=[], realized=[], misc={}))
        db.commit()
        assert json.loads(body(export_year(2026, format="json", db=db)))["plan_contributions"] == []
