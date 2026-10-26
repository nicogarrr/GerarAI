"""Backfilled snapshots must relink returns and rebase external-flow windows.

Synthetic EUR cash-only portfolio; no quotes, providers, workers or real data.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, CashBalance, Transaction
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.portfolio_snapshot_service import PortfolioSnapshotService

D0, D1, D2, D3 = [date(2026, 1, day) for day in range(1, 5)]


@pytest.fixture
def state():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "synthetic-backfill"
        portfolio = PortfolioFXService().ensure_portfolio(db)
        cash = CashBalance(currency="EUR", balance=Decimal("1000"), as_of=D0)
        db.add(cash)
        db.flush()
        yield db, portfolio, cash
    engine.dispose()


def capture(db, cash, day, balance):
    cash.as_of = day
    cash.balance = Decimal(balance)
    db.flush()
    return PortfolioSnapshotService().capture(db, as_of=day)


def test_new_middle_snapshot_relinks_interval_return_and_descendants(state):
    db, _, cash = state
    capture(db, cash, D0, "1000")
    second = capture(db, cash, D2, "1210")
    last = capture(db, cash, D3, "1331")
    assert second.daily_return == pytest.approx(Decimal("0.21"))
    capture(db, cash, D1, "1100")
    assert second.daily_return == pytest.approx(Decimal("0.10"))
    assert second.metadata_["interval_days"] == 1
    assert second.cumulative_twr == pytest.approx(Decimal("0.21"))
    assert last.cumulative_twr == pytest.approx(Decimal("0.331"))


def test_backfill_resolves_gap_flow_without_counting_deposit_twice(state):
    db, portfolio, cash = state
    capture(db, cash, D0, "1000")
    db.add(Transaction(portfolio_id=portfolio.id, trade_date=D1, action="deposit",
                       quantity=Decimal("1"), price=Decimal("500"), currency="EUR"))
    db.flush()
    second = capture(db, cash, D2, "1760")
    last = capture(db, cash, D3, "1936")
    assert second.daily_return is None
    assert second.net_external_flow_base == Decimal("500")
    middle = capture(db, cash, D1, "1600")
    assert middle.daily_return == pytest.approx(Decimal("0.10"))
    assert second.net_external_flow_base == Decimal("0")
    assert second.metadata_["unvalued_intermediate_flows"] == 0
    assert second.metadata_["twr_blocked_by_gap_flows"] is False
    assert second.daily_return == pytest.approx(Decimal("0.10"))
    assert second.cumulative_twr == pytest.approx(Decimal("0.21"))
    assert last.cumulative_twr == pytest.approx(Decimal("0.331"))


def test_new_earliest_snapshot_gives_old_first_its_return(state):
    db, _, cash = state
    second = capture(db, cash, D1, "1100")
    last = capture(db, cash, D2, "1210")
    assert second.daily_return is None
    capture(db, cash, D0, "1000")
    assert second.daily_return == pytest.approx(Decimal("0.10"))
    assert last.cumulative_twr == pytest.approx(Decimal("0.21"))


def test_relink_does_not_upgrade_legacy_flow_evidence(state):
    db, _, cash = state
    capture(db, cash, D0, "1000")
    later = capture(db, cash, D2, "1210")
    later.metadata_ = {}
    db.flush()
    capture(db, cash, D1, "1100")
    assert later.daily_return is None
    assert later.cumulative_twr is None


def test_recapture_relinks_without_revaluing_later_snapshots(state):
    db, _, cash = state
    capture(db, cash, D0, "1000")
    capture(db, cash, D1, "1100")
    last = capture(db, cash, D2, "1210")
    capture(db, cash, D1, "1000")
    assert last.total_value_base == Decimal("1210")
    assert last.daily_return == pytest.approx(Decimal("0.21"))
    assert last.cumulative_twr == pytest.approx(Decimal("0.21"))


@pytest.mark.parametrize("action,currency", [("cash_misc", "EUR"), ("deposit", "USD")])
def test_backfill_does_not_unblock_ambiguous_or_missing_fx_flows(state, action, currency):
    db, portfolio, cash = state
    capture(db, cash, D0, "1000")
    db.add(Transaction(portfolio_id=portfolio.id, trade_date=D2, action=action,
                       quantity=Decimal("1"), price=Decimal("500"), currency=currency))
    db.flush()
    last = capture(db, cash, D2, "1760")
    capture(db, cash, D1, "1600")
    assert last.daily_return is None
    assert last.cumulative_twr is None
    assert last.metadata_["ambiguous_external_flows"]


def test_backfill_with_remaining_unvalued_flow_gap_stays_blocked(state):
    db, portfolio, cash = state
    capture(db, cash, D0, "1000")
    db.add(Transaction(portfolio_id=portfolio.id, trade_date=D2, action="deposit",
                       quantity=Decimal("1"), price=Decimal("500"), currency="EUR"))
    db.flush()
    last = capture(db, cash, D3, "1936")
    capture(db, cash, D1, "1100")
    assert last.daily_return is None
    assert last.cumulative_twr is None
    assert last.metadata_["unvalued_intermediate_flows"] == 1
    assert last.metadata_["interval_days"] == 2
