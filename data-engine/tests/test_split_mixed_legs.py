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
    _apply(db, c, "2", date(2025, 6, 1))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.quantity == Decimal("40")          # 10*2 + 20 ; buggy code gives 60
    # total cost unchanged: 10*100 + 20*50 = 2000 -> avg 50
    assert pos.average_cost == Decimal("50")      # buggy code gives 30/2=... avg/ratio


PRICE_AS_OF = date(2025, 12, 31)


def _apply(db, c, ratio, eff, price="25", as_of=PRICE_AS_OF):
    return CorporateActionService().create_action(
        db, ticker=c.ticker, action_type="split", effective_date=eff, ratio=Decimal(ratio),
        post_split_price=Decimal(price) if price is not None else None,
        post_split_price_as_of=as_of)


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
    assert pos.cost_basis_native == Decimal("5600")
    assert abs(pos.average_cost - Decimal("13.658537")) < Decimal("0.000001")


def test_ledger_reverse_split_basic_and_idempotent(db):
    c = _company(db)
    _buy(db, c, "100", "2", date(2025, 1, 10))
    db.commit()
    a = _apply(db, c, "0.1", date(2025, 6, 1))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.quantity == Decimal("10")
    assert pos.average_cost == Decimal("20")
    assert pos.cost_basis_native == Decimal("200")
    CorporateActionService().apply_action(db, a.id)
    assert db.query(Position).filter_by(company_id=c.id).one().quantity == Decimal("10")


def test_ledger_extreme_reverse_split_one_to_million(db):
    c = _company(db)
    _buy(db, c, "1000000", "0.02", date(2025, 1, 10))
    db.commit()
    _apply(db, c, "0.000001", date(2025, 6, 1))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.quantity == Decimal("1")
    assert pos.average_cost == Decimal("20000")
    assert pos.cost_basis_native == Decimal("20000")


def test_ledger_split_with_no_post_legs_scales_whole_position(db):
    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    db.commit()
    _apply(db, c, "4", date(2025, 6, 1))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.quantity == Decimal("40")
    assert pos.average_cost == Decimal("25")
    assert pos.cost_basis_native == Decimal("1000")


def _snapshot(pos):
    from sqlalchemy.orm import object_session
    object_session(pos).expire_all()
    return {
        k: getattr(pos, k)
        for k in (
            "quantity", "average_cost", "market_price", "market_value", "unrealized_pnl",
            "realized_pnl", "cost_basis_native", "cost_basis_base", "realized_pnl_base",
            "unrealized_pnl_base", "market_value_base", "fx_rate", "as_of",
        )
    }


def test_post_split_sell_updates_base_fx_and_unrealized_like_rebuild(db):
    from app.models.entities import FXRate
    from app.services.portfolio_fx_service import PortfolioFXService

    c = _company(db)
    base = PortfolioFXService().ensure_portfolio(db).base_currency.upper()
    if base != "USD":
        db.add(FXRate(base_currency=base, quote_currency="USD", rate=Decimal("0.9"),
                      rate_date=date(2024, 1, 1), source="test"))
    db.commit()
    rate = Decimal("1") if base == "USD" else Decimal("0.9")
    _buy(db, c, "10", "100", date(2025, 1, 10))
    _sell(db, c, "5", "50", date(2025, 7, 10))
    db.commit()
    _apply(db, c, "2", date(2025, 6, 1))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.cost_basis_native == Decimal("750")
    assert pos.realized_pnl == Decimal("0")
    assert pos.cost_basis_base == Decimal("750") * rate
    assert pos.realized_pnl_base == Decimal("0")
    assert pos.unrealized_pnl == pos.market_value - pos.cost_basis_native
    before = _snapshot(pos)
    from app.services.portfolio_ledger_service import PortfolioLedgerService
    PortfolioLedgerService().rebuild_position(db, c.id)
    after = _snapshot(db.query(Position).filter_by(company_id=c.id).one())
    assert after == before


def test_split_without_verified_price_rejects_before_any_write(db):
    import pytest

    from app.models.entities import CorporateAction, Transaction
    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    pos.market_price = Decimal("120")  # sin proveniencia: pre o post split?
    pos.as_of = date(2025, 5, 1)
    db.commit()
    with pytest.raises(ValueError, match="no provenance"):
        _apply(db, c, "4", date(2025, 6, 1), price=None)
    assert db.query(CorporateAction).count() == 0
    tx = db.query(Transaction).filter_by(company_id=c.id).one()
    assert tx.quantity == Decimal("10") and tx.price == Decimal("100")
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.quantity == Decimal("10")
    assert pos.market_price == Decimal("120") and pos.as_of == date(2025, 5, 1)


def test_split_uses_exactly_the_supplied_verified_price_and_date(db):
    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    pos.market_price = Decimal("120")
    pos.as_of = date(2025, 5, 1)
    db.commit()
    _apply(db, c, "4", date(2025, 6, 1), price="31", as_of=date(2025, 6, 2))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.market_price == Decimal("31")
    assert pos.as_of == date(2025, 6, 2)
    assert pos.market_value == Decimal("40") * Decimal("31")


def test_failed_apply_now_leaves_no_residual_action(db):
    import pytest

    from app.models.entities import CorporateAction
    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    pos.quantity = Decimal("11")
    db.commit()
    with pytest.raises(ValueError):
        _apply(db, c, "2", date(2025, 6, 1))
    assert db.query(CorporateAction).count() == 0
    CorporateActionService().create_action(
        db, ticker=c.ticker, action_type="split", effective_date=date(2025, 6, 1),
        ratio=Decimal("2"), apply_now=False)
    row = db.query(CorporateAction).one()
    assert row.applied is False


def test_ledger_apply_is_idempotent_and_delete_blocked_after_apply(db):
    import pytest

    from app.models.entities import Transaction
    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    db.commit()
    service = CorporateActionService()
    action = _apply(db, c, "2", date(2025, 6, 1))
    service.apply_action(db, action.id)
    tx = db.query(Transaction).filter_by(company_id=c.id).one()
    assert tx.quantity == Decimal("20.000000")
    assert db.query(Position).filter_by(company_id=c.id).one().quantity == Decimal("20")
    with pytest.raises(ValueError, match="immutable"):
        service.delete_action(db, action.id)


def test_ratio_3_with_fees_and_pre_post_sells_matches_rebuild(db):
    from app.services.portfolio_ledger_service import PortfolioLedgerService
    c = _company(db)
    svc = PortfolioLedgerService()
    svc.create_transaction(db, ticker=c.ticker, action="buy", quantity=Decimal("9"),
                           price=Decimal("90"), fees=Decimal("3"),
                           trade_date=date(2025, 1, 10), currency="USD")
    _sell(db, c, "3", "100", date(2025, 2, 10))
    _buy(db, c, "30", "35", date(2025, 7, 1))
    _sell(db, c, "6", "40", date(2025, 8, 1))
    db.commit()
    _apply(db, c, "3", date(2025, 6, 1))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.quantity == Decimal("18") + Decimal("30") + Decimal("0") - Decimal("6")
    before = _snapshot(pos)
    svc.rebuild_position(db, c.id)
    assert _snapshot(db.query(Position).filter_by(company_id=c.id).one()) == before


def test_reverse_one_third_matches_rebuild_with_quantization(db):
    from app.services.portfolio_ledger_service import PortfolioLedgerService
    c = _company(db)
    _buy(db, c, "30", "10", date(2025, 1, 10))
    db.commit()
    CorporateActionService().create_action(
        db, ticker=c.ticker, action_type="reverse_split",
        effective_date=date(2025, 6, 1), ratio=Decimal(1) / Decimal(3),
        post_split_price=Decimal("30"), post_split_price_as_of=PRICE_AS_OF)
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.quantity == Decimal("10")
    assert pos.cost_basis_native == Decimal("300")
    before = _snapshot(pos)
    PortfolioLedgerService().rebuild_position(db, c.id)
    assert _snapshot(db.query(Position).filter_by(company_id=c.id).one()) == before


def test_adjusted_replay_oversell_by_quantization_rejects_with_rollback(db):
    import pytest

    from app.models.entities import CorporateAction, Transaction
    c = _company(db)
    _buy(db, c, "1", "10", date(2025, 1, 10))
    _buy(db, c, "1", "10", date(2025, 1, 11))
    _sell(db, c, "1", "10", date(2025, 7, 1))
    db.commit()
    with pytest.raises(ValueError, match="oversell"):
        CorporateActionService().create_action(
            db, ticker=c.ticker, action_type="reverse_split",
            effective_date=date(2025, 6, 1), ratio=Decimal("0.333333"),
            post_split_price=Decimal("30"), post_split_price_as_of=PRICE_AS_OF)
    assert db.query(CorporateAction).count() == 0
    qtys = sorted(t.quantity for t in db.query(Transaction).filter_by(company_id=c.id))
    assert qtys == [Decimal("1"), Decimal("1"), Decimal("1")]
    assert db.query(Position).filter_by(company_id=c.id).one().quantity == Decimal("1")


def test_mixed_currency_ledger_rolls_back_split_completely(db):
    import pytest

    from app.models.entities import CorporateAction, Transaction
    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    db.add(Transaction(
        company_id=c.id, trade_date=date(2025, 7, 1), action="buy",
        quantity=Decimal("5"), price=Decimal("90"), fees=Decimal("0"), currency="EUR"))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    pos.quantity = Decimal("15")
    db.commit()
    with pytest.raises(Exception, match="mix"):
        _apply(db, c, "2", date(2025, 6, 1))
    assert db.query(CorporateAction).count() == 0
    pre = db.query(Transaction).filter_by(company_id=c.id, currency="USD").one()
    assert pre.quantity == Decimal("10") and pre.price == Decimal("100")
    assert db.query(Position).filter_by(company_id=c.id).one().quantity == Decimal("15")


def test_closed_position_reverse_split_rejects_quantization_oversell(db):
    import pytest

    from app.models.entities import CorporateAction, Transaction
    c = _company(db)
    _buy(db, c, "10", "10", date(2025, 1, 10))
    _buy(db, c, "10", "10", date(2025, 1, 11))
    _sell(db, c, "20", "10", date(2025, 2, 1))
    db.commit()
    assert db.query(Position).filter_by(company_id=c.id).count() == 0
    with pytest.raises(ValueError, match="oversell"):
        CorporateActionService().create_action(
            db, ticker=c.ticker, action_type="reverse_split",
            effective_date=date(2025, 6, 1), ratio=Decimal(1) / Decimal(3))
    assert db.query(CorporateAction).count() == 0
    qtys = sorted(t.quantity for t in db.query(Transaction).filter_by(company_id=c.id))
    assert qtys == [Decimal("10"), Decimal("10"), Decimal("20")]


def test_closed_position_split_rescales_legs_and_rebuild_still_works(db):
    from app.models.entities import Transaction
    from app.services.portfolio_ledger_service import PortfolioLedgerService
    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    _sell(db, c, "10", "120", date(2025, 2, 1))
    db.commit()
    CorporateActionService().create_action(
        db, ticker=c.ticker, action_type="split", effective_date=date(2025, 6, 1),
        ratio=Decimal("2"))
    qtys = sorted(t.quantity for t in db.query(Transaction).filter_by(company_id=c.id))
    assert qtys == [Decimal("20"), Decimal("20")]
    assert PortfolioLedgerService().rebuild_position(db, c.id) is None


def test_closed_position_with_mixed_currencies_rejected_without_writes(db):
    import pytest

    from app.models.entities import CorporateAction, Transaction
    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    _sell(db, c, "10", "100", date(2025, 2, 1))
    db.add(Transaction(
        company_id=c.id, trade_date=date(2025, 3, 1), action="buy", quantity=Decimal("1"),
        price=Decimal("1"), fees=Decimal("0"), currency="EUR"))
    db.add(Transaction(
        company_id=c.id, trade_date=date(2025, 3, 2), action="sell", quantity=Decimal("1"),
        price=Decimal("1"), fees=Decimal("0"), currency="EUR"))
    db.commit()
    with pytest.raises(ValueError, match="mixes currencies"):
        CorporateActionService().create_action(
            db, ticker=c.ticker, action_type="split", effective_date=date(2025, 6, 1),
            ratio=Decimal("2"))
    assert db.query(CorporateAction).count() == 0
    first = db.query(Transaction).filter_by(company_id=c.id, currency="USD", action="buy").one()
    assert first.quantity == Decimal("10")


def test_ledger_split_rescales_buy_and_sell_legs_but_not_cash_or_post_legs(db):
    from app.models.entities import Transaction
    c = _company(db)
    _buy(db, c, "10", "100", date(2026, 1, 10))
    _sell(db, c, "4", "150", date(2026, 2, 10))
    db.add(Transaction(
        company_id=c.id, trade_date=date(2026, 3, 1), action="dividend",
        quantity=Decimal("1"), price=Decimal("25"), fees=Decimal("0"), currency="USD"))
    _buy(db, c, "2", "40", date(2026, 7, 1))
    db.commit()
    _apply(db, c, "4", date(2026, 6, 1), price="40", as_of=date(2026, 7, 2))
    rows = {(t.action, t.trade_date): t for t in db.query(Transaction).filter_by(company_id=c.id)}
    buy = rows[("buy", date(2026, 1, 10))]
    sell = rows[("sell", date(2026, 2, 10))]
    assert (buy.quantity, buy.price) == (Decimal("40"), Decimal("25"))
    assert (sell.quantity, sell.price) == (Decimal("16"), Decimal("37.5"))
    assert rows[("dividend", date(2026, 3, 1))].price == Decimal("25")
    post = rows[("buy", date(2026, 7, 1))]
    assert (post.quantity, post.price) == (Decimal("2"), Decimal("40"))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.quantity == Decimal("26")
