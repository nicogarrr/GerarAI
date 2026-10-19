import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.alerts import ManualAlertCreate, create_alert
from app.models.entities import Base, Company


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker, name, exchange, company_type):
    c = Company(ticker=ticker, name=name, exchange=exchange, currency="USD", sector="Unknown",
                industry="Unknown", company_type=company_type, valuation_model="unassigned",
                special_sources=[], special_risks=[], factor_tags=[])
    db.add(c)
    db.commit()
    return c


def test_alert_on_unrecognised_stub_symbol_is_rejected(db):
    _company(db, "ZZZZ9", "ZZZZ9", "UNKNOWN", "research_candidate")
    with pytest.raises(HTTPException) as exc:
        create_alert(ManualAlertCreate(ticker="ZZZZ9", alert_type="price_above", operator=">", value=100), db)
    assert exc.value.status_code == 422
    assert "ZZZZ9" in exc.value.detail


def test_alert_on_enriched_company_is_created(db):
    _company(db, "AAPL", "Apple Inc", "NASDAQ NMS - GLOBAL MARKET", "research_candidate")
    rule = create_alert(ManualAlertCreate(ticker="AAPL", alert_type="price_above", operator=">", value=300), db)
    assert rule.id is not None
