"""Splits: cierre diario almacenado (market_prices, yfinance) como precio post-split.

Los fixtures demuestran la LOGICA sobre datos elegidos; no la fiabilidad del feed real.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.entities import CorporateAction, MarketPrice, Position
from app.services.corporate_actions_service import CorporateActionService
from app.services.portfolio_ledger_service import PortfolioLedgerService
from tests.test_dividend_ingestion import _company, db  # noqa: F401

TODAY = date.today()
EFF = TODAY - timedelta(days=5)


def _setup(db, ratio="2"):
    c = _company(db)
    PortfolioLedgerService().create_transaction(
        db, ticker=c.ticker, action="buy", quantity=Decimal("10"), price=Decimal("100"),
        trade_date=EFF - timedelta(days=60), currency="USD")
    db.commit()
    a = CorporateActionService().create_action(
        db, ticker=c.ticker, action_type="split", effective_date=EFF, ratio=Decimal(ratio), apply_now=False)
    return c, a


def _bar(db, c, d, close, source="yfinance", adj="close"):
    db.add(MarketPrice(company_id=c.id, date=d, open=close, high=close, low=close, close=Decimal(close),
                       adj_close=Decimal(close) if adj == "close" else None, volume=1, source=source))
    db.commit()


def test_applies_with_latest_stored_close_and_records_provenance(db):
    c, a = _setup(db)
    _bar(db, c, EFF, "52")
    _bar(db, c, TODAY - timedelta(days=1), "51")
    CorporateActionService().apply_action(db, a.id)
    p = db.query(Position).filter_by(company_id=c.id).one()
    assert p.quantity == Decimal("20") and p.market_price == Decimal("51")
    assert p.as_of == TODAY - timedelta(days=1)
    act = db.get(CorporateAction, a.id)
    assert act.applied and "yfinance" in act.description and "no contrastada" in act.description


@pytest.mark.parametrize("case", ["no_bars", "spot_only", "other_source", "before_effective"])
def test_fails_closed_without_a_verifiable_close(db, case):
    c, a = _setup(db)
    if case == "spot_only":
        _bar(db, c, TODAY - timedelta(days=1), "51", adj=None)
    elif case == "other_source":
        _bar(db, c, TODAY - timedelta(days=1), "51", source="finnhub")
    elif case == "before_effective":
        _bar(db, c, EFF - timedelta(days=1), "104")
    with pytest.raises(ValueError, match="provenance"):
        CorporateActionService().apply_action(db, a.id)
    db.rollback()
    assert db.query(Position).filter_by(company_id=c.id).one().quantity == Decimal("10")
    assert not db.get(CorporateAction, a.id).applied


def test_stale_close_is_rejected(db):
    c = _company(db)
    old_eff = TODAY - timedelta(days=60)
    PortfolioLedgerService().create_transaction(
        db, ticker=c.ticker, action="buy", quantity=Decimal("10"), price=Decimal("100"),
        trade_date=old_eff - timedelta(days=30), currency="USD")
    db.commit()
    a = CorporateActionService().create_action(
        db, ticker=c.ticker, action_type="split", effective_date=old_eff, ratio=Decimal("2"), apply_now=False)
    _bar(db, c, old_eff + timedelta(days=1), "50")
    with pytest.raises(ValueError, match="provenance"):
        CorporateActionService().apply_action(db, a.id)


def test_jump_compatible_with_ratio_in_window_is_rejected(db):
    c, a = _setup(db, "2")
    _bar(db, c, EFF, "100")
    _bar(db, c, EFF + timedelta(days=2), "50")  # la barra "efectiva" seguia en terminos pre-split
    with pytest.raises(ValueError, match="provenance"):
        CorporateActionService().apply_action(db, a.id)


def test_later_split_blocks(db):
    c, a = _setup(db)
    _bar(db, c, TODAY - timedelta(days=1), "25")
    CorporateActionService().create_action(
        db, ticker=c.ticker, action_type="split", effective_date=TODAY - timedelta(days=2),
        ratio=Decimal("2"), apply_now=False)
    with pytest.raises(ValueError, match="provenance"):
        CorporateActionService().apply_action(db, a.id)


def test_explicit_caller_price_is_untouched_by_the_resolver(db):
    c, a = _setup(db)
    _bar(db, c, TODAY - timedelta(days=1), "51")
    CorporateActionService().apply_action(
        db, a.id, post_split_price=Decimal("77"), post_split_price_as_of=TODAY - timedelta(days=1))
    assert db.query(Position).filter_by(company_id=c.id).one().market_price == Decimal("77")
