"""Un ratio de split que la columna guarda como 0 se rechaza (400), no da 500.

``ratio`` se guarda en Numeric(24, 10). Un ratio > 0 por debajo de 1e-10 (p. ej.
1e-320) pasaba el «> 0», al aplicar el split dividía el precio por él y saltaba
``decimal.InvalidOperation`` (500); sin aplicar quedaba guardado como 0.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import corporate_actions
from app.core.database import Base, get_db
from app.models import CorporateAction
from app.services.corporate_actions_service import CorporateActionService
from tests.test_corporate_actions_service import _company, _tx, db  # noqa: F401


@pytest.mark.parametrize("ratio", ["1e-320", "0.00000000001", "0.00000000004"])
@pytest.mark.parametrize("apply_now", [True, False])
def test_ratio_that_rounds_to_zero_is_rejected(db, ratio, apply_now):  # noqa: F811
    company = _company(db)
    _tx(db, company, date(2025, 1, 2), "buy", 10, 5)
    with pytest.raises(ValueError, match="positive"):
        CorporateActionService().create_action(
            db, ticker="AAA", action_type="split", effective_date=date(2025, 6, 1),
            ratio=Decimal(ratio), apply_now=apply_now,
        )
    assert db.query(CorporateAction).count() == 0


def test_smallest_stored_ratio_is_still_accepted(db):  # noqa: F811
    _company(db)
    action = CorporateActionService().create_action(
        db, ticker="AAA", action_type="split", effective_date=date(2025, 6, 1),
        ratio=Decimal("0.0000000001"), apply_now=False,
    )
    assert action.ratio == Decimal("0.0000000001")


def test_route_answers_400_instead_of_500():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        company = _company(session)
        _tx(session, company, date(2025, 1, 2), "buy", 10, 5)

    def _db():
        with factory() as session:
            session.info["tenant_id"] = "tenant-test"
            yield session

    app = FastAPI()
    app.include_router(corporate_actions.router, prefix="/corporate-actions")
    app.dependency_overrides[get_db] = _db
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/corporate-actions",
        json={"ticker": "AAA", "action_type": "split", "effective_date": "2025-06-01", "ratio": 1e-320},
    )
    assert response.status_code == 400
    with Session(engine) as session:
        assert session.query(CorporateAction).count() == 0
