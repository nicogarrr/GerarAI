"""Read-only native-currency canary, not an automatic cost repair.

Only an all-buy native Flex ledger with matching shares is comparable. Sales
need broker lot accounting (the general ledger currently uses weighted average),
so this canary deliberately refuses to replay them. No FX is used here.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Position, Transaction
from app.services.portfolio_fx_service import currency_key

COST_ABSOLUTE_TOLERANCE = Decimal("0.05")
COST_RELATIVE_TOLERANCE = Decimal("0.001")  # 0.1%, plus a five-cent floor
QUANTITY_TOLERANCE = Decimal("0.000001")
REVIEW_MESSAGE = (
    "Coste pendiente de revisión: el extracto de posiciones de IBKR no coincide "
    "con las compras importadas. Coste y rentabilidad no disponibles hasta conciliar."
)


def reconcile_ibkr_costs(db: Session, positions: list[Position]) -> dict[int, dict]:
    candidates = [p for p in positions if p.source == "ibkr_flex" and p.quantity > 0]
    if not candidates:
        return {}
    by_company = defaultdict(list)
    for trade in db.scalars(select(Transaction).where(
        Transaction.company_id.in_({p.company_id for p in candidates}),
        Transaction.action.in_(["buy", "sell", "split"]),
        *tenant_filters(db, Transaction),
    )):
        by_company[trade.company_id].append(trade)
    result = {}
    for p in candidates:
        trades = [t for t in by_company[p.company_id]
                  if t.portfolio_id == p.portfolio_id and t.trade_date <= p.as_of]
        reason = None
        if not trades:
            reason = "no_native_trades"
        elif any(t.action != "buy" for t in trades):
            reason = "sales_or_adjustments"
        elif any(not any((t.raw_payload or {}).get(key)
                         for key in ("tradeID", "ibExecID", "transactionID")) for t in trades):
            reason = "non_native_trades"
        elif any(t.quantity <= 0 or t.price <= 0 or t.fees < 0 for t in trades):
            reason = "invalid_trade_values"
        elif len({(t.raw_payload or {}).get("accountId") for t in trades}) > 1:
            reason = "multiple_accounts"
        elif any(currency_key(t.currency) != currency_key(p.currency)
                 or ((t.raw_payload or {}).get("ibCommissionCurrency")
                     and currency_key(t.raw_payload["ibCommissionCurrency"]) != currency_key(p.currency))
                 for t in trades):
            reason = "currency_mismatch"
        elif abs(sum((t.quantity for t in trades), Decimal("0")) - p.quantity) > QUANTITY_TOLERANCE:
            reason = "quantity_mismatch"
        elif p.cost_basis_native is None or p.cost_basis_native <= 0:
            reason = "missing_snapshot_cost"
        if reason:
            result[p.id] = {"status": "not_comparable", "reason": reason}
            continue
        cost = sum((t.quantity * t.price + t.fees for t in trades), Decimal("0"))
        tolerance = max(COST_ABSOLUTE_TOLERANCE, abs(cost) * COST_RELATIVE_TOLERANCE)
        delta = p.cost_basis_native - cost
        result[p.id] = {
            "status": "review_required" if abs(delta) > tolerance else "ok",
            "reason": "ibkr_cost_mismatch" if abs(delta) > tolerance else None,
            "message": REVIEW_MESSAGE if abs(delta) > tolerance else None,
            "snapshot_cost_native": float(p.cost_basis_native),
            "trade_cost_native": float(cost), "difference_native": float(delta),
            "tolerance_native": float(tolerance), "currency": p.currency,
        }
    return result


def mask_cost_under_review(payload: dict, review: dict | None) -> dict:
    """Keep valuation visible; never return conflicting costs/profits as facts."""
    payload["cost_reconciliation"] = review
    if review and review["status"] == "review_required":
        for field in ("average_cost", "cost_basis", "cost_basis_native", "cost_basis_base",
                      "unrealized_pnl", "unrealized_pnl_native", "unrealized_pnl_base",
                      "pnl_price_effect_base", "pnl_fx_effect_base"):
            payload[field] = None
    return payload
