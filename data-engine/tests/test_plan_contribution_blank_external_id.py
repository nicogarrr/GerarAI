"""external_id vacío o en blanco no es una referencia de importación.

Schemathesis: POST /api/plan/contributions con ``external_id=""`` dos veces daba
500 (UNIQUE tenant/plan/external_id). ``if external_id:`` se saltaba la
comprobación de idempotencia pero guardaba ``""``, así que la segunda aportación
manual sin referencia chocaba con la primera.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base
from app.services.investment_plan_service import InvestmentPlanService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


@pytest.fixture
def service(db):
    service = InvestmentPlanService()
    service.upsert_plan(
        db,
        monthly_contribution=Decimal("300"),
        monthly_contribution_currency="EUR",
        start_date=date(2026, 1, 1),
        horizon_years=30,
        target_allocations=[],
    )
    return service


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_external_id_is_no_reference(db, service, blank):
    first = service.add_contribution(db, date_=date(2026, 9, 1), amount=Decimal("300"), external_id=blank)
    second = service.add_contribution(db, date_=date(2026, 10, 1), amount=Decimal("250"), external_id=blank)
    assert first.id != second.id
    assert first.external_id is None and second.external_id is None
    assert len(service.list_contributions(db)) == 2


def test_external_id_is_trimmed_so_retries_stay_idempotent(db, service):
    first = service.add_contribution(db, date_=date(2026, 9, 1), amount=Decimal("300"), external_id="broker-7")
    again = service.add_contribution(db, date_=date(2026, 9, 1), amount=Decimal("300"), external_id=" broker-7 ")
    assert again.id == first.id
    assert len(service.list_contributions(db)) == 1
