"""Read-only cost canary. Synthetic Flex, never a customer export."""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Position, Tenant, Transaction
from app.services.ibkr_import_service import IBKRImportService


def xml(*, cost="108.396746", quantity="6.0572", trades_first=False, currency="USD"):
    position = f'<OpenPosition accountId="U1" costBasisCurrency="USD" symbol="BABA" position="{quantity}" markPrice="130" costBasisPrice="{cost}" currency="USD" reportDate="2026-10-27"/>'
    trades = f'<Trade accountId="U1" symbol="BABA" tradeID="B1" buySell="BUY" quantity="6.0572" tradePrice="125.56" ibCommission="0.047968" currency="{currency}" tradeDate="2026-10-01"/>'
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


def test_explicit_base_cost_uses_each_buy_historical_fx_not_snapshot_fx(db):
    source = xml().replace('costBasisCurrency="USD"', 'costBasisCurrency="EUR" costBasisMoney="656.580769"')
    source = source.replace('tradeID="B1"', 'tradeID="B1" baseCurrency="EUR" fxRateToBase="0.8"')
    source = source.replace('quantity="6.0572" tradePrice="125.56" ibCommission="0.047968"',
                            'quantity="3" tradePrice="100" ibCommission="0"')
    source = source.replace('</FlexStatement>', '<Trade accountId="U1" symbol="BABA" tradeID="B2" buySell="BUY" quantity="3.0572" tradePrice="150.6580468585633913384796546" ibCommission="0" currency="USD" baseCurrency="EUR" fxRateToBase="0.9044468157672824419558816913" tradeDate="2026-10-02"/></FlexStatement>')
    result = IBKRImportService().import_flex_xml(db, source)
    from app.services.ibkr_cost_reconciliation import mask_cost_under_review, reconcile_ibkr_costs
    p = db.query(Position).one()
    review = reconcile_ibkr_costs(db, [p])[p.id]
    assert result["cost_review_required"] == []
    assert review["status"] == "ok"
    assert review["currency"] == "EUR"
    assert review["trade_cost_native"] == pytest.approx(656.580769, abs=.01)
    # Read-only reconciliation must not silently serve an EUR cost as USD.
    assert mask_cost_under_review({"average_cost": 108.396746, "market_value": 800}, review)["average_cost"] is None
    assert p.average_cost == Decimal("108.396746")


def test_ambiguous_baba_cost_is_nd_not_a_false_mismatch(db):
    source = xml().replace('costBasisCurrency="USD" ', '')
    source = source.replace('tradeID="B1"', 'tradeID="B1" baseCurrency="EUR" fxRateToBase="0.863251909030332"')
    IBKRImportService().import_flex_xml(db, source)
    from app.services.ibkr_cost_reconciliation import mask_cost_under_review, reconcile_ibkr_costs
    p = db.query(Position).one()
    review = reconcile_ibkr_costs(db, [p])[p.id]
    assert review["status"] == "not_comparable"
    assert review["reason"] == "unknown_cost_currency"
    assert mask_cost_under_review({"average_cost": 108.396746}, review)["average_cost"] is None


def test_missing_raw_snapshot_is_nd_even_if_stored_currency_says_usd(db):
    IBKRImportService().import_flex_xml(db, xml())
    from app.models import IbkrRawRow
    db.query(IbkrRawRow).delete()
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    p = db.query(Position).one()
    assert reconcile_ibkr_costs(db, [p])[p.id]["reason"] == "missing_snapshot_evidence"


@pytest.mark.parametrize("rate", [None, "0", "NaN", "-1", "Infinity"])
def test_base_cost_requires_valid_historical_fx_on_every_buy(db, rate):
    source = xml().replace('costBasisCurrency="USD"', 'costBasisCurrency="EUR"')
    if rate is not None:
        source = source.replace('tradeID="B1"', f'tradeID="B1" baseCurrency="EUR" fxRateToBase="{rate}"')
    IBKRImportService().import_flex_xml(db, source)
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    p = db.query(Position).one()
    assert reconcile_ibkr_costs(db, [p])[p.id]["reason"] == "missing_trade_fx_evidence"


def test_genuine_base_currency_mismatch_is_flagged(db):
    source = xml().replace('costBasisCurrency="USD"', 'costBasisCurrency="EUR"')
    source = source.replace('tradeID="B1"', 'tradeID="B1" baseCurrency="EUR" fxRateToBase="0.7"')
    result = IBKRImportService().import_flex_xml(db, source)
    assert result["cost_review_required"] == ["BABA"]


def test_contradictory_raw_cost_money_is_nd(db):
    source = xml().replace('costBasisCurrency="USD"', 'costBasisCurrency="USD" costBasisMoney="999"')
    IBKRImportService().import_flex_xml(db, source)
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    p = db.query(Position).one()
    assert reconcile_ibkr_costs(db, [p])[p.id]["status"] == "not_comparable"


def test_raw_from_foreign_tenant_is_not_snapshot_evidence(db):
    IBKRImportService().import_flex_xml(db, xml())
    from app.models import IbkrRawRow
    other = Tenant(external_id="raw-foreign", name="raw-foreign")
    db.add(other)
    db.flush()
    local_tenant = db.info["tenant_id"]
    evidence = [(row.account_id, row.section, row.path, row.row_hash, row.payload)
                for row in db.query(IbkrRawRow).all()]
    db.query(IbkrRawRow).delete()
    db.info["tenant_id"] = other.id
    for account, section, path, digest, payload in evidence:
        db.add(IbkrRawRow(account_id=account, section=section, path=path, row_hash=digest, payload=payload))
    db.flush()
    db.info["tenant_id"] = local_tenant
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    p = db.query(Position).one()
    assert reconcile_ibkr_costs(db, [p])[p.id]["reason"] == "missing_snapshot_evidence"


def test_two_matching_raw_rows_are_ambiguous_not_latest_wins(db):
    source = xml()
    IBKRImportService().import_flex_xml(db, source)
    IBKRImportService().import_flex_xml(db, source.replace('costBasisCurrency="USD"', 'costBasisCurrency="EUR"'))
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    p = db.query(Position).one()
    assert reconcile_ibkr_costs(db, [p])[p.id]["reason"] == "ambiguous_snapshot_evidence"


def test_missing_fx_destination_does_not_assume_portfolio_base(db):
    source = xml().replace('costBasisCurrency="USD"', 'costBasisCurrency="EUR"')
    source = source.replace('tradeID="B1"', 'tradeID="B1" fxRateToBase="0.8632"')
    IBKRImportService().import_flex_xml(db, source)
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    p = db.query(Position).one()
    assert reconcile_ibkr_costs(db, [p])[p.id]["reason"] == "missing_trade_fx_evidence"


def test_native_raw_cost_and_native_trades_can_corroborate_currency(db):
    source = xml(cost="125.57").replace('costBasisCurrency="USD" ', '')
    IBKRImportService().import_flex_xml(db, source)
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    p = db.query(Position).one()
    assert reconcile_ibkr_costs(db, [p])[p.id]["status"] == "ok"


def test_snapshot_from_other_account_is_not_evidence(db):
    IBKRImportService().import_flex_xml(db, xml().replace('OpenPosition accountId="U1"', 'OpenPosition accountId="U2"'))
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    p = db.query(Position).one()
    assert reconcile_ibkr_costs(db, [p])[p.id]["reason"] == "snapshot_account_mismatch"


def test_quality_counts_unverified_costs_without_claiming_mismatch(db):
    source = xml().replace('costBasisCurrency="USD" ', '')
    IBKRImportService().import_flex_xml(db, source)
    from app.services.portfolio_quality_service import portfolio_quality
    quality = portfolio_quality(db)
    assert quality["cost_review_positions"] == 0
    assert quality["cost_unverified_positions"] == 1
    assert "ibkr_cost_currency_unverified" in quality["reasons"]


def test_non_eur_base_is_not_guessed_to_be_eur(db):
    from app.models import Portfolio
    db.add(Portfolio(name="Main", base_currency="CHF", is_default=True))
    db.flush()
    source = xml().replace('costBasisCurrency="USD"', 'costBasisCurrency="CHF"')
    source = source.replace('tradeID="B1"', 'tradeID="B1" baseCurrency="CHF" fxRateToBase="0.863251909030332"')
    IBKRImportService().import_flex_xml(db, source)
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    p = db.query(Position).one()
    review = reconcile_ibkr_costs(db, [p])[p.id]
    assert review["status"] == "ok"
    assert review["currency"] == "CHF"


def test_conflicting_cost_currency_attributes_are_nd(db):
    source = xml().replace('costBasisCurrency="USD"', 'costBasisCurrency="USD" costBasisMoneyCurrency="EUR"')
    IBKRImportService().import_flex_xml(db, source)
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    p = db.query(Position).one()
    assert reconcile_ibkr_costs(db, [p])[p.id]["reason"] == "contradictory_cost_currency"


def test_baba_nine_purchase_synthetic_matches_reported_historical_base_total(db):
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs
    usd_total = Decimal("760.591780856")
    eur_total = Decimal("656.58076956379116")
    trades = []
    for i in range(9):
        qty = Decimal(".6") if i < 8 else Decimal("1.2572")
        amount = Decimal("80") if i < 8 else usd_total - Decimal("640")
        rate = Decimal(".85") if i < 8 else (eur_total - Decimal("544")) / amount
        trades.append(f'<Trade accountId="U1" symbol="BABA" tradeID="B{i}" buySell="BUY" quantity="{qty}" tradePrice="{amount / qty}" currency="USD" ibCommission="0" baseCurrency="EUR" fxRateToBase="{rate}" tradeDate="2026-10-01"/>')
    import re
    source = re.sub(r'<Trade [^>]*/>', ''.join(trades), xml())
    source = source.replace('costBasisCurrency="USD"', 'costBasisCurrency="EUR" costBasisMoney="656.580769"')
    result = IBKRImportService().import_flex_xml(db, source)
    p = db.query(Position).one()
    review = reconcile_ibkr_costs(db, [p])[p.id]
    assert db.query(Transaction).count() == 9
    assert review["status"] == "ok" and result["cost_review_required"] == []
    assert review["trade_cost_native"] == pytest.approx(float(eur_total), abs=.00001)
    assert p.cost_basis_native == Decimal("656.580770")


@pytest.mark.parametrize("reconcile", [False, True])
def test_dry_run_never_commits_or_writes(db, reconcile):
    """dry_run es solo lectura en TODAS las rutas (antes reconcile=False hacia commit)."""
    from sqlalchemy import func, select

    from app.models import CashBalance, IbkrRawRow, PortfolioDailySnapshot

    options = {"reconcile": True, "expected_account_id": "U1", "max_statement_age_days": 36500} if reconcile else {}
    statement = xml().replace(
        "<FlexStatement>", '<FlexStatement accountId="U1" fromDate="20261001" toDate="20261027">'
    )
    result = IBKRImportService().import_flex_xml(db, statement, dry_run=True, **options)
    assert result["status"] == "dry_run"
    db.expire_all()
    for model in (Position, Transaction, CashBalance, IbkrRawRow, PortfolioDailySnapshot):
        assert db.scalar(select(func.count()).select_from(model)) == 0, model.__name__


def test_dry_run_commit_is_never_called(db, monkeypatch):
    calls = []
    monkeypatch.setattr(db, "commit", lambda: calls.append("commit"))
    IBKRImportService().import_flex_xml(db, xml(), dry_run=True)
    assert calls == []
    # y sin dry_run si confirma: el contrato no rompe el import normal.
    IBKRImportService().import_flex_xml(db, xml())
    assert calls and set(calls) == {"commit"}
