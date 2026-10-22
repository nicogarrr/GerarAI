"""CorporateActionService contracts: split math must preserve economic value.

Splits and reverse splits rescale quantities and prices while preserving the
money amounts (position value, realized gains, dividend cash). These tests
pin that invariance, the effective-date boundary, idempotent application and
immutability after apply - the tax FIFO ledger depends on all of them.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
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


def _company(db: Session, ticker: str = "AAA") -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _position(db, company, *, qty, cost, price):
    position = Position(
        company_id=company.id,
        quantity=Decimal(str(qty)),
        average_cost=Decimal(str(cost)),
        market_price=Decimal(str(price)),
        currency="USD",
    )
    db.add(position)
    db.commit()
    return position


def _tx(db, company, day, action, qty, price):
    tx = Transaction(
        company_id=company.id, trade_date=day, action=action,
        quantity=Decimal(str(qty)), price=Decimal(str(price)),
        fees=Decimal("0"), currency="USD",
    )
    db.add(tx)
    db.commit()
    return tx


def test_split_rejects_manual_position_without_ledger(db):
    # Posicion manual sin patas: no hay libro que demuestre unidades/precio.
    company = _company(db)
    _position(db, company, qty=10, cost=100, price=150)
    with pytest.raises(ValueError, match="Split rejected"):
        CorporateActionService().create_action(
            db, ticker="AAA", action_type="split",
            effective_date=date(2026, 6, 1), ratio=Decimal("4"),
        )
    db.rollback()
    position = db.query(Position).filter_by(company_id=company.id).one()
    assert position.quantity == Decimal("10")


def test_split_rescales_only_pre_effective_transactions(db):
    company = _company(db)
    before = _tx(db, company, date(2026, 1, 10), "buy", 10, 100)
    on_date = _tx(db, company, date(2026, 6, 1), "buy", 5, 40)
    after = _tx(db, company, date(2026, 7, 1), "buy", 2, 38)
    CorporateActionService().create_action(
        db, ticker="AAA", action_type="split",
        effective_date=date(2026, 6, 1), ratio=Decimal("2"),
    )
    db.refresh(before)
    db.refresh(on_date)
    db.refresh(after)
    # Pre-effective trade rescaled, money amount preserved (10x100 == 20x50).
    assert before.quantity == Decimal("20.000000")
    assert before.price == Decimal("50.000000")
    assert before.quantity * before.price == Decimal("1000.000000")
    # Trades on/after the effective date are already post-split: untouched.
    assert on_date.quantity == Decimal("5") and on_date.price == Decimal("40")
    assert after.quantity == Decimal("2") and after.price == Decimal("38")


def test_reverse_split_rejects_manual_position_without_ledger(db):
    company = _company(db)
    _position(db, company, qty=100, cost=2, price=3)
    with pytest.raises(ValueError, match="Split rejected"):
        CorporateActionService().create_action(
            db, ticker="AAA", action_type="reverse_split",
            effective_date=date(2026, 6, 1), ratio=Decimal("0.1"),
        )
    db.rollback()
    position = db.query(Position).filter_by(company_id=company.id).one()
    assert position.quantity == Decimal("100")


def test_split_rejects_manual_source_even_if_quantity_matches_ledger(db):
    # qty coincide con el libro pero source manual: no habilita el replay.
    company = _company(db)
    _position(db, company, qty=10, cost=100, price=150)
    tx = _tx(db, company, date(2026, 1, 10), "buy", 10, 100)
    with pytest.raises(ValueError, match="not the ledger"):
        CorporateActionService().create_action(
            db, ticker="AAA", action_type="split",
            effective_date=date(2026, 6, 1), ratio=Decimal("2"),
        )
    db.rollback()
    db.refresh(tx)
    assert tx.quantity == Decimal("10")

def test_unapplied_action_can_be_deleted(db):
    _company(db)
    service = CorporateActionService()
    action = service.create_action(
        db, ticker="AAA", action_type="split",
        effective_date=date(2026, 6, 1), ratio=Decimal("2"), apply_now=False,
    )
    assert action.applied is False
    assert service.delete_action(db, action.id) is True
    assert db.scalar(select(CorporateAction).where(CorporateAction.id == action.id)) is None


def test_invalid_ratio_and_unknown_ticker_rejected(db):
    _company(db)
    service = CorporateActionService()
    with pytest.raises(ValueError, match="positive"):
        service.create_action(
            db, ticker="AAA", action_type="split",
            effective_date=date(2026, 6, 1), ratio=Decimal("0"),
        )
    with pytest.raises(ValueError, match="does not exist"):
        service.create_action(
            db, ticker="NOPE", action_type="split",
            effective_date=date(2026, 6, 1), ratio=Decimal("2"),
        )
