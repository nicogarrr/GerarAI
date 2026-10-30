"""Divisa de las aportaciones del plan: ISO de 3 letras y en mayusculas.

Antes «eur» se guardaba tal cual (y un reintento con «EUR» y la misma
referencia daba 409) y «EURO» se aceptaba aunque nunca tendra tipo de cambio.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.models.entities import Base
from app.services.investment_plan_service import InvestmentPlanService
from main import app
from tests.test_investment_plan_service import _plan


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def test_lowercase_currency_is_stored_upper_and_retry_is_idempotent(db):
    service = InvestmentPlanService()
    _plan(service, db)
    first = service.add_contribution(db, date_=date(2026, 3, 1), amount=Decimal("100"), currency="eur", external_id="r1")
    assert first.currency == "EUR"
    again = service.add_contribution(db, date_=date(2026, 3, 1), amount=Decimal("100"), currency="EUR", external_id="r1")
    assert again.id == first.id


@pytest.mark.parametrize("bad", ["EURO", "€", "E1R", ""])
def test_api_rejects_non_iso_currency(db, bad):
    _plan(InvestmentPlanService(), db)
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).post(
            "/api/plan/contributions", json={"date": "2026-03-01", "amount": 100, "currency": bad}
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 422
