"""Split with post-split legs already on the ledger (NOT RUN by the author).
Reuses the in-memory sqlite fixture/helpers pattern of tests/test_dividend_ingestion.py.
Expected values are the economically correct ones; both tests FAIL on 088cd14d if the risk is real.
"""
from datetime import date
from decimal import Decimal

from app.models.entities import Position
from app.services.corporate_actions_service import CorporateActionService
from app.services.portfolio_ledger_service import PortfolioLedgerService
from tests.test_dividend_ingestion import _company, db  # noqa: F401


def _buy(db, company, qty, price, d):
    # create_transaction rejects future dates; use past dates only
    return PortfolioLedgerService().create_transaction(
        db, ticker=company.ticker, action="buy", quantity=Decimal(qty), price=Decimal(price),
        trade_date=d, currency="USD")


def test_split_applied_after_post_split_buy_keeps_post_split_shares(db):
    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))   # pre-split leg: 10 sh @100
    _buy(db, c, "20", "50", date(2025, 7, 10))    # post-split leg already in post-split terms
    db.commit()
    CorporateActionService().create_action(
        db, ticker=c.ticker, action_type="split", effective_date=date(2025, 6, 1), ratio=Decimal("2"))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.quantity == Decimal("40")          # 10*2 + 20 ; buggy code gives 60
    # total cost unchanged: 10*100 + 20*50 = 2000 -> avg 50
    assert pos.average_cost == Decimal("50")      # buggy code gives 30/2=... avg/ratio


def _apply(db, c, ratio, eff):
    return CorporateActionService().create_action(
        db, ticker=c.ticker, action_type="split", effective_date=eff, ratio=Decimal(ratio))


def _sell(db, company, qty, price, d):
    return PortfolioLedgerService().create_transaction(
        db, ticker=company.ticker, action="sell", quantity=Decimal(qty), price=Decimal(price),
        trade_date=d, currency="USD")


def test_post_split_sell_of_pre_split_shares_replays_cost(db):
    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    _sell(db, c, "5", "50", date(2025, 7, 10))
    db.commit()
    _apply(db, c, "2", date(2025, 6, 1))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.quantity == Decimal("15")
    assert pos.average_cost == Decimal("50")
    assert pos.realized_pnl == Decimal("0")


def test_split_rejects_position_ledger_mismatch_without_writes(db):
    import pytest

    from app.models.entities import Transaction
    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    pos.quantity = Decimal("11")
    db.commit()
    with pytest.raises(ValueError, match="does not match the ledger"):
        _apply(db, c, "2", date(2025, 6, 1))
    db.rollback()
    tx = db.query(Transaction).filter_by(company_id=c.id).one()
    assert tx.quantity == Decimal("10")
    assert db.query(Position).filter_by(company_id=c.id).one().quantity == Decimal("11")


def test_split_consistent_fixture_110_gives_410_cost_5600(db):
    c = _company(db)
    _buy(db, c, "100", "50", date(2025, 1, 10))
    _buy(db, c, "10", "60", date(2025, 7, 10))
    db.commit()
    _apply(db, c, "4", date(2025, 6, 1))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.quantity == Decimal("410")
    assert pos.cost_basis_native == pos.quantity * pos.average_cost
    assert abs(pos.quantity * pos.average_cost - Decimal("5600")) < Decimal("0.01")
    assert abs(pos.average_cost - Decimal("13.658537")) < Decimal("0.000001")
