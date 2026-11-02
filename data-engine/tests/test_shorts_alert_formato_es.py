"""Aviso «Posiciones cortas en aumento»: cifras en formato español."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Company, Position, ResearchAlert, Tenant
from app.models.entities import Base
from app.services.short_positions_service import emit_shorts_increase


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="owner"))
        session.commit()
        session.info.update(tenant_id=1, user_id="owner")
        yield session
    engine.dispose()


def _held(db, ticker):
    company = Company(ticker=ticker, name=ticker, exchange="X", company_type="compounders", valuation_model="dcf")
    db.add(company)
    db.commit()
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    return company


def test_finra_share_counts_use_spanish_thousands(db):
    company = _held(db, "ACME")
    now = datetime.now(UTC)
    payload = {"short_interest": {"previous_short_interest": 12345678, "short_interest": 13000000,
                                  "settlement_date": now.date().isoformat(), "source_url": "https://www.finra.org/"}}
    emit_shorts_increase(db, company, {}, payload, now)
    db.commit()
    message = db.scalar(select(ResearchAlert)).message
    assert "FINRA 12.345.678 → 13.000.000 acciones" in message


def test_cnmv_percentages_use_decimal_comma(db):
    company = _held(db, "ACX.MC")
    now = datetime.now(UTC)
    day0 = (now - timedelta(days=10)).date().isoformat()
    day1 = (now - timedelta(days=2)).date().isoformat()
    previous = {"source": "CNMV", "public_total_percent": 0.52,
                "positions": [{"holder": "Fondo A", "position_date": day0, "percent": 0.52}]}
    current = {"source": "CNMV", "public_total_percent": 0.61, "source_url": "https://www.cnmv.es/",
               "positions": [{"holder": "Fondo A", "position_date": day1, "percent": 0.61}]}
    emit_shorts_increase(db, company, previous, current, now)
    db.commit()
    message = db.scalar(select(ResearchAlert)).message
    assert "CNMV 0,52% → 0,61%" in message
    assert "0.52" not in message
