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


def test_split_without_verified_price_applies_accounting_and_holds_valuation(db):
    from app.models.entities import CorporateAction, Transaction
    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    pos = db.query(Position).filter_by(company_id=c.id).one()
    pos.market_price = Decimal("120")  # sin proveniencia: pre o post split?
    pos.as_of = date(2025, 5, 1)
    db.commit()
    _apply(db, c, "4", date(2025, 6, 1), price=None, as_of=None)
    assert db.query(CorporateAction).one().applied
    tx = db.query(Transaction).filter_by(company_id=c.id).one()
    assert tx.quantity == Decimal("40") and tx.price == Decimal("25")
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.quantity == Decimal("40") and pos.average_cost == Decimal("25")
    # Valoracion suspendida de forma persistente: ni el precio guardado (120, pre-split)
    # ni uno inferido del ratio; valores NULL, as_of sin mover.
    assert pos.valuation_hold_reason and "sin precio post-split verificado" in pos.valuation_hold_reason
    assert pos.valuation_hold_effective_date == date(2025, 6, 1)
    assert pos.market_price == Decimal("0") and pos.market_value == Decimal("0")
    assert pos.market_value_base is None and pos.market_value_native is None
    assert pos.unrealized_pnl_base is None
    assert pos.as_of == date(2025, 5, 1)


def test_hold_survives_rebuild_and_market_refresh_and_only_a_verified_price_releases_it(db):
    import pytest

    from app.services.portfolio_ledger_service import PortfolioLedgerService
    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    db.commit()
    _apply(db, c, "2", date(2025, 6, 1), price=None, as_of=None)
    ledger = PortfolioLedgerService()
    _buy(db, c, "1", "55", date(2025, 7, 1))  # una operacion posterior reconstruye la posicion
    db.commit()
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.valuation_hold_reason and pos.market_price == Decimal("0") and pos.market_value_base is None
    # un refresco con un precio cualquiera (p. ej. cache pre-split) NO levanta ni reescribe
    from app.services.portfolio_ledger_service import ValuationHeldError
    with pytest.raises(ValuationHeldError):
        ledger.update_market_price(db, company_id=c.id, price=Decimal("120"), as_of=date(2025, 12, 1))
    db.rollback()
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.valuation_hold_reason and pos.market_price == Decimal("0")
    # liberar exige hold, precio Decimal valido y fecha >= efectiva
    with pytest.raises(ValueError):
        ledger.release_valuation_hold(db, company_id=c.id, price=Decimal("60"), as_of=date(2025, 5, 1))
    with pytest.raises(ValueError):
        ledger.release_valuation_hold(db, company_id=c.id, price=60.0, as_of=date(2025, 12, 1))
    db.rollback()
    ledger.release_valuation_hold(db, company_id=c.id, price=Decimal("60"), as_of=date(2025, 12, 1))
    db.commit()
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.valuation_hold_reason is None and pos.market_price == Decimal("60")
    assert pos.market_value == pos.quantity * Decimal("60")
    with pytest.raises(ValueError):
        ledger.release_valuation_hold(db, company_id=c.id, price=Decimal("61"), as_of=date(2025, 12, 2))


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


def _bad_price_case(db, price, as_of):
    import pytest

    from app.models.entities import Company, CorporateAction, Transaction
    c = db.query(Company).first() or _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    db.commit()
    with pytest.raises(ValueError, match="Split rejected"):
        CorporateActionService().create_action(
            db, ticker=c.ticker, action_type="split", effective_date=date(2025, 6, 1),
            ratio=Decimal("2"), post_split_price=price, post_split_price_as_of=as_of)
    assert db.query(CorporateAction).count() == 0
    tx = db.query(Transaction).filter_by(company_id=c.id).one()
    assert tx.quantity == Decimal("10") and tx.price == Decimal("100")
    assert db.query(Position).filter_by(company_id=c.id).one().quantity == Decimal("10")


def test_split_rejects_invalid_verified_price_inputs_before_writes(db):
    from datetime import datetime
    good = date(2025, 12, 31)
    for price, as_of in [
        (25.0, good),                      # float
        (25, good),                        # int
        (Decimal("NaN"), good),
        (Decimal("Infinity"), good),
        (Decimal("0"), good),
        (Decimal("-1"), good),
        (Decimal("25"), None),             # sin fecha
        (Decimal("25"), datetime(2025, 12, 31)),   # datetime, no date
        (Decimal("25"), "2025-12-31"),
        (Decimal("25"), date(2025, 5, 31)),        # anterior al efectivo
    ]:
        _bad_price_case(db, price, as_of)
        db.rollback()
        db.query(Position).delete()
        from app.models.entities import Transaction
        db.query(Transaction).delete()
        db.commit()


def test_split_rejects_future_verified_price_date_with_fixed_clock(db, monkeypatch):
    import app.services.corporate_actions_service as mod
    monkeypatch.setattr(mod, "_today", lambda: date(2025, 12, 1))
    _bad_price_case(db, Decimal("25"), date(2025, 12, 2))
    monkeypatch.setattr(mod, "_today", lambda: date(2025, 12, 2))
    db.rollback()
    c = db.query(__import__("app.models.entities", fromlist=["Company"]).Company).one()
    CorporateActionService().create_action(
        db, ticker=c.ticker, action_type="split", effective_date=date(2025, 6, 1),
        ratio=Decimal("2"), post_split_price=Decimal("25"),
        post_split_price_as_of=date(2025, 12, 2))
    assert db.query(Position).filter_by(company_id=c.id).one().quantity == Decimal("20")


def test_http_route_ignores_post_split_fields_and_does_not_enable_bypass(db):
    from app.api.routes.corporate_actions import (
        CorporateActionInput,
        create_action,
    )
    from app.models.entities import CorporateAction, Transaction

    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    db.commit()
    body = {
        "ticker": c.ticker, "action_type": "split", "effective_date": "2025-06-01",
        "ratio": 2, "post_split_price": "25", "post_split_price_as_of": "2025-12-01",
    }
    # El modelo del endpoint no declara esos campos: se descartan, no habilitan nada.
    assert "post_split_price" not in CorporateActionInput.model_fields
    # El precio del cliente se descarta: se aplica la contabilidad y la valoracion
    # queda en suspenso (25 no se usa como precio de mercado).
    create_action(CorporateActionInput(**body), db)
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.valuation_hold_reason and pos.market_price != Decimal("25")
    assert db.query(CorporateAction).count() == 1
    assert db.query(Transaction).filter_by(company_id=c.id).one().quantity == Decimal("20")


def test_hold_consumers_risk_alert_snapshot_and_api_do_not_present_a_zero_quote(db):
    from app.api.routes.portfolio import positions as list_positions
    from app.services.risk_service import RiskService

    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    db.commit()
    _apply(db, c, "2", date(2025, 6, 1), price=None, as_of=None)
    db.commit()
    risk = RiskService().dashboard(db)
    assert [h["ticker"] for h in risk["valuation_hold"]] == [c.ticker]
    assert risk["status"] == "incomplete_valuation"
    # El endpoint devuelve el sobre paginado (items + page_info), no la lista.
    rows = list_positions(limit=500, offset=0, db=db)["items"]
    row = next(r for r in rows if r["ticker"] == c.ticker)
    assert row["market_price"] is None and row["market_value"] is None
    assert row["market_value_native"] is None and row["unrealized_pnl_native"] is None
    assert row["valuation_hold"]["effective_date"] == "2025-06-01"


def test_hold_alert_observation_ignores_the_zero_sentinel(db):
    from types import SimpleNamespace

    from app.services.alert_rule_service import AlertRuleService

    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    db.commit()
    _apply(db, c, "2", date(2025, 6, 1), price=None, as_of=None)
    db.commit()
    # nosemgrep: gerarai-orm-fake-simplenamespace -- _observe solo lee rule.company_id y rule.target; la consulta real va contra precios
    rule = SimpleNamespace(company_id=c.id, target={"kind": "market_price"})
    value, info = AlertRuleService()._observe(db, rule)
    assert value is None and info["status"] == "missing"


def test_price_update_on_held_position_is_an_explicit_error_not_a_silent_noop(db):
    import pytest

    from app.services.portfolio_ledger_service import PortfolioLedgerService, ValuationHeldError

    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    db.commit()
    _apply(db, c, "2", date(2025, 6, 1), price=None, as_of=None)
    db.commit()
    with pytest.raises(ValuationHeldError, match="on hold"):
        PortfolioLedgerService().update_market_price(db, company_id=c.id, price=Decimal("60"), as_of=date(2025, 12, 1))


def test_manual_price_route_returns_409_on_held_position(db):
    import pytest
    from fastapi import HTTPException

    from app.api.routes.portfolio import PortfolioPriceInput, update_price

    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    db.commit()
    _apply(db, c, "2", date(2025, 6, 1), price=None, as_of=None)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        update_price(PortfolioPriceInput(ticker=c.ticker, price=Decimal("60"), as_of=date(2025, 12, 1)), db)
    assert exc.value.status_code == 409


def test_summary_carries_the_hold(db):
    from app.api.routes.portfolio import portfolio_summary

    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    db.commit()
    _apply(db, c, "2", date(2025, 6, 1), price=None, as_of=None)
    db.commit()
    summary = portfolio_summary(db)
    assert [h["ticker"] for h in summary["valuation_hold"]] == [c.ticker]
    assert summary["status"] in {"incomplete_valuation", "incomplete_fx"}


def test_ibkr_flex_import_keeps_the_hold_and_reports_it(db):
    from app.services.ibkr_import_service import IBKRImportService

    c = _company(db)
    _buy(db, c, "10", "100", date(2025, 1, 10))
    db.commit()
    _apply(db, c, "2", date(2025, 6, 1), price=None, as_of=None)
    db.commit()
    xml = (
        '<FlexQueryResponse><FlexStatements><FlexStatement><OpenPositions>'
        f'<OpenPosition symbol="{c.ticker}" position="20" markPrice="60" positionValue="1200" '
        'costBasisPrice="50" currency="USD" reportDate="2025-12-01"/>'
        '</OpenPositions></FlexStatement></FlexStatements></FlexQueryResponse>'
    )
    result = IBKRImportService().import_flex_xml(db, xml)
    pos = db.query(Position).filter_by(company_id=c.id).one()
    assert pos.valuation_hold_reason and pos.market_price == Decimal("0") and pos.market_value_base is None
    assert result["valuation_hold_kept"] == [c.ticker]
