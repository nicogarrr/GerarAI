"""F-CA1: un split anterior a la primera operacion de la posicion ya esta
reflejado (las acciones se compraron post-split). Aplicarlo no debe reescalar
la posicion actual; uno posterior a la primera compra si se aplica."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, CorporateAction, Position, Transaction
from app.services.corporate_actions_service import CorporateActionService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _setup(db: Session):
    company = Company(
        ticker="AAPL", name="AAPL", exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    db.add(Position(
        company_id=company.id, quantity=Decimal("100"), average_cost=Decimal("50"),
        market_price=Decimal("60"), currency="USD",
    ))
    db.add(Transaction(
        company_id=company.id, trade_date=date(2021, 3, 1), action="buy",
        quantity=Decimal("100"), price=Decimal("50"), fees=Decimal("0"), currency="USD",
    ))
    db.commit()
    return company


def _split(db, company, day, ratio):
    action = CorporateAction(
        company_id=company.id, action_type="split", effective_date=day,
        ratio=Decimal(ratio), description="x", applied=False, source="yahoo_finance",
    )
    db.add(action)
    db.commit()
    return action


def test_historical_split_does_not_rescale_current_position(db):
    company = _setup(db)
    old = _split(db, company, date(2005, 2, 28), "2")
    service = CorporateActionService()
    first = service.first_trade_dates(db, {company.id})[company.id]
    assert service.is_historical(old, first) is True
    service.apply_action(db, old.id)
    position = db.query(Position).filter_by(company_id=company.id).one()
    assert position.quantity == Decimal("100")
    assert position.average_cost == Decimal("50")
    assert db.get(CorporateAction, old.id).applied is True


def test_split_after_first_trade_rejects_manual_source_position(db):
    company = _setup(db)
    recent = _split(db, company, date(2022, 6, 1), "4")
    service = CorporateActionService()
    first = service.first_trade_dates(db, {company.id})[company.id]
    assert service.is_historical(recent, first) is False
    # Posicion de fixture con source manual: se rechaza sin escribir (el caso
    # ledger coherente esta en tests/test_split_mixed_legs.py).
    with pytest.raises(ValueError, match="not the ledger"):
        service.apply_action(db, recent.id)
    db.rollback()
    position = db.query(Position).filter_by(company_id=company.id).one()
    assert position.quantity == Decimal("100")
    assert position.average_cost == Decimal("50")


def test_no_transactions_is_not_historical(db):
    company = _setup(db)
    db.query(Transaction).delete()
    db.commit()
    action = _split(db, company, date(2005, 2, 28), "2")
    service = CorporateActionService()
    assert service.first_trade_dates(db, {company.id}) == {}
    assert service.is_historical(action, None) is False


def test_company_outside_portfolio_has_no_holding(db):
    held = _setup(db)
    other = Company(
        ticker="MSFT", name="MSFT", exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(other)
    db.commit()
    service = CorporateActionService()
    assert service.companies_with_holding(db, {held.id, other.id}) == {held.id}
    assert service.companies_with_holding(db, set()) == set()


def test_list_payload_marks_no_position(db):
    from app.api.routes.corporate_actions import _payload

    held = _setup(db)
    action = _split(db, held, date(2022, 6, 1), "4")
    assert _payload(action, "AAPL", None, has_holding=False)["no_position"] is True
    assert _payload(action, "AAPL", None, has_holding=True)["no_position"] is False
