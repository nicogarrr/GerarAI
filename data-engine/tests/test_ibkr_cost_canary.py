"""Read-only cost canary. Synthetic Flex, never a customer export."""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Position, Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService


def xml(*, cost="108.396746", quantity="6.0572", trades_first=False, currency="USD"):
    position = f'<OpenPosition symbol="BABA" position="{quantity}" markPrice="130" costBasisPrice="{cost}" currency="USD" reportDate="2026-10-27"/>'
    trades = f'<Trade symbol="BABA" tradeID="B1" buySell="BUY" quantity="6.0572" tradePrice="125.56" ibCommission="0.047968" currency="{currency}" tradeDate="2026-10-01"/>'
    body = trades + position if trades_first else position + trades
    return f'<FlexQueryResponse><FlexStatements><FlexStatement>{body}</FlexStatement></FlexStatements></FlexQueryResponse>'


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        tenant = Tenant(external_id="canary", name="canary")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        yield session
    engine.dispose()


@pytest.mark.parametrize("trades_first", [False, True])
def test_import_flags_conflicting_cost_without_rewriting_snapshot(db, trades_first):
    result = IBKRImportService().import_flex_xml(db, xml(trades_first=trades_first))
    assert result["cost_review_required"] == ["BABA"]
    p = db.query(Position).one()
    assert p.average_cost == Decimal("108.396746")
    assert p.cost_basis_native == Decimal("656.580770")
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    review = reconcile_ibkr_costs(db, [p])[p.id]
    assert review["status"] == "review_required"
    assert review["trade_cost_native"] == pytest.approx(760.59, abs=.01)


def test_matching_cost_and_rounding_do_not_raise_false_alarm(db):
    result = IBKRImportService().import_flex_xml(db, xml(cost="125.57"))
    assert result["cost_review_required"] == []


@pytest.mark.parametrize("change,reason", [
    ({"quantity": "10"}, "quantity_mismatch"),
    ({"currency": "EUR"}, "currency_mismatch"),
])
def test_partial_or_different_currency_ledger_is_not_compared(db, change, reason):
    IBKRImportService().import_flex_xml(db, xml(**change))
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    p = db.query(Position).one()
    review = reconcile_ibkr_costs(db, [p])[p.id]
    assert review == {"status": "not_comparable", "reason": reason}


def test_trade_backfill_detected_on_read_and_quality_marks_incomplete(db):
    IBKRImportService().import_flex_xml(db, xml())
    from app.services.portfolio_quality_service import portfolio_quality
    quality = portfolio_quality(db)
    assert quality["cost_review_positions"] == 1
    assert "ibkr_cost_mismatch" in quality["reasons"]


def test_foreign_tenant_trades_never_participate(db):
    IBKRImportService().import_flex_xml(db, xml())
    local = db.query(Position).one()
    # Switching to a separate authenticated tenant must hide the local ledger.
    other = Tenant(external_id="other-canary", name="other")
    db.add(other)
    db.flush()
    db.info["tenant_id"] = other.id
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    assert reconcile_ibkr_costs(db, [local])[local.id]["status"] == "not_comparable"


def test_sells_not_replayed_with_wrong_cost_method(db):
    IBKRImportService().import_flex_xml(db, xml())
    trade = db.query(Transaction).one()
    trade.action = "sell"
    db.flush()
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    p = db.query(Position).one()
    assert reconcile_ibkr_costs(db, [p])[p.id]["reason"] == "sales_or_adjustments"


def test_payload_masks_cost_and_profit_but_preserves_market_value(db):
    IBKRImportService().import_flex_xml(db, xml())
    from app.services.ibkr_cost_reconciliation import mask_cost_under_review, reconcile_ibkr_costs
    p = db.query(Position).one()
    review = reconcile_ibkr_costs(db, [p])[p.id]
    payload = mask_cost_under_review({"market_value": 800, "average_cost": 108.396746,
                                    "unrealized_pnl_base": 143}, review)
    assert payload["market_value"] == 800
    assert payload["average_cost"] is None
    assert payload["unrealized_pnl_base"] is None
    assert "revisión" in payload["cost_reconciliation"]["message"]
    assert p.average_cost == Decimal("108.396746")


def test_positions_api_hides_conflict_and_shows_review(db):
    IBKRImportService().import_flex_xml(db, xml())
    from app.api.routes.portfolio import positions
    row = positions(limit=100, offset=0, db=db)[0]
    assert row["ticker"] == "BABA"
    assert row["average_cost"] is None
    assert row["cost_basis_native"] is None
    assert row["unrealized_pnl_base"] is None
    assert row["market_value"] > 0
    assert row["cost_reconciliation"]["status"] == "review_required"


def test_backfill_after_snapshot_is_rechecked_without_mutation(db):
    source = xml()
    import re
    snapshot_only = re.sub(r'<Trade [^>]*/>', '', source)
    svc = IBKRImportService()
    svc.import_flex_xml(db, snapshot_only)
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    p = db.query(Position).one()
    assert reconcile_ibkr_costs(db, [p])[p.id]["status"] == "not_comparable"
    svc.import_flex_xml(db, source, trades_only=True)
    assert reconcile_ibkr_costs(db, [p])[p.id]["status"] == "review_required"
    assert p.average_cost == Decimal("108.396746")


def test_future_trade_is_excluded_from_snapshot_comparison(db):
    IBKRImportService().import_flex_xml(db, xml().replace('tradeDate="2026-10-01"', 'tradeDate="2026-10-28"'))
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    p = db.query(Position).one()
    assert reconcile_ibkr_costs(db, [p])[p.id]["reason"] == "no_native_trades"
