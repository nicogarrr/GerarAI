"""Read-only cost canary. Never guess the unit of a stored broker cost.

Only native all-buy Flex ledgers with matching shares are comparable. Historical
FX comes from each purchase, never today or the position report date. Raw rows
are evidence, not instructions or permission to repair persisted amounts.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import IbkrRawRow, Position, Transaction
from app.services.portfolio_fx_service import currency_key

COST_ABSOLUTE_TOLERANCE = Decimal("0.05")
COST_RELATIVE_TOLERANCE = Decimal("0.001")  # 0.1%, plus a five-cent floor
QUANTITY_TOLERANCE = Decimal("0.000001")
REVIEW_MESSAGE = (
    "Coste pendiente de revisión: el extracto de posiciones de IBKR no coincide "
    "con las compras importadas. Coste y rentabilidad no disponibles hasta conciliar."
)


UNKNOWN_MESSAGE = (
    "Divisa del coste de IBKR sin verificar. Coste y rentabilidad no disponibles "
    "hasta disponer de un extracto con evidencia suficiente."
)


def _number(value) -> Decimal | None:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _close(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= max(COST_ABSOLUTE_TOLERANCE, abs(right) * COST_RELATIVE_TOLERANCE)


def _snapshot_evidence(p: Position, trades: list[Transaction], rows: list[IbkrRawRow]):
    accounts = {(t.raw_payload or {}).get("accountId") for t in trades}
    if len(accounts) != 1 or not next(iter(accounts)):
        return None, "missing_account_evidence"
    account = next(iter(accounts))
    matches = []
    for row in rows:
        raw = row.payload
        if raw.get("symbol") != p.company.ticker:
            continue
        if raw.get("levelOfDetail", "SUMMARY").upper() != "SUMMARY":
            continue
        day = str(raw.get("reportDate") or raw.get("asOfDate") or "").split(";", 1)[0]
        try:
            report_date = datetime.strptime(day.replace("-", ""), "%Y%m%d").date()
        except ValueError:
            continue
        qty = _number(raw.get("position", raw.get("quantity")))
        price = _number(raw.get("costBasisPrice", raw.get("costPrice", raw.get("avgPrice"))))
        if report_date != p.as_of or qty is None or price is None:
            continue
        if abs(qty - p.quantity) > QUANTITY_TOLERANCE:
            continue
        if currency_key(raw.get("currency", "")) != currency_key(p.currency):
            continue
        if p.cost_basis_native is None or not _close(qty * price, p.cost_basis_native):
            continue
        matches.append(row)
    if not matches:
        return None, "missing_snapshot_evidence"
    # Do not choose the latest corrected row: no explicit link to the snapshot.
    if len(matches) != 1:
        return None, "ambiguous_snapshot_evidence"
    if matches[0].account_id != account:
        return None, "snapshot_account_mismatch"
    raw = matches[0].payload
    money = _number(raw.get("costBasisMoney"))
    if "costBasisMoney" in raw and (money is None or not _close(money, p.cost_basis_native)):
        return None, "contradictory_snapshot_cost"
    return raw, None


def _trade_cost_in_currency(trades: list[Transaction], currency: str, base: str) -> Decimal | None:
    total = Decimal("0")
    for trade in trades:
        amount = trade.quantity * trade.price + trade.fees
        if currency_key(trade.currency) == currency_key(currency):
            total += amount
            continue
        if currency_key(currency) != currency_key(base):
            return None
        raw = trade.raw_payload or {}
        # fxRateToBase alone does not identify its destination currency.
        if currency_key(raw.get("baseCurrency", "")) != currency_key(base):
            return None
        rate = _number(raw.get("fxRateToBase"))
        if rate is None or rate <= 0:
            return None
        total += amount * rate
    return total


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
    # Las filas crudas se guardan todas (prueba fiscal) y crecen con cada sync:
    # solo se leen las del dia y ticker de cada posicion candidata (indice
    # ix_ibkr_raw_rows_snapshot), no el historico entero del tenant.
    raw_rows = list(db.scalars(select(IbkrRawRow).where(
        IbkrRawRow.path.in_(["OpenPosition", "OpenPositions/OpenPosition"]),
        IbkrRawRow.report_date.in_({p.as_of for p in candidates}),
        IbkrRawRow.symbol.in_({p.company.ticker for p in candidates}),
        *tenant_filters(db, IbkrRawRow),
    )))
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
        raw, reason = _snapshot_evidence(p, trades, raw_rows)
        if reason:
            result[p.id] = {"status": "not_comparable", "reason": reason, "message": UNKNOWN_MESSAGE}
            continue
        assert raw is not None
        currencies = {currency_key(raw[key]) for key in ("costBasisCurrency", "costBasisMoneyCurrency")
                      if raw.get(key)}
        if len(currencies) > 1:
            result[p.id] = {"status": "not_comparable", "reason": "contradictory_cost_currency", "message": UNKNOWN_MESSAGE}
            continue
        currency = raw.get("costBasisCurrency") or raw.get("costBasisMoneyCurrency")
        if not currency:
            # Currency labels the position, not necessarily its cost. Agreement
            # with the native ledger can corroborate it, but a discrepancy cannot.
            native = _trade_cost_in_currency(trades, p.currency, p.base_currency)
            if native is None or not _close(p.cost_basis_native, native):
                result[p.id] = {"status": "not_comparable", "reason": "unknown_cost_currency", "message": UNKNOWN_MESSAGE}
                continue
            currency = raw["currency"]
        cost = _trade_cost_in_currency(trades, currency, p.base_currency)
        if cost is None:
            result[p.id] = {"status": "not_comparable", "reason": "missing_trade_fx_evidence", "message": UNKNOWN_MESSAGE}
            continue
        tolerance = max(COST_ABSOLUTE_TOLERANCE, abs(cost) * COST_RELATIVE_TOLERANCE)
        delta = p.cost_basis_native - cost
        result[p.id] = {
            "status": "review_required" if abs(delta) > tolerance else "ok",
            "reason": "ibkr_cost_mismatch" if abs(delta) > tolerance else None,
            "message": REVIEW_MESSAGE if abs(delta) > tolerance else None,
            "snapshot_cost_native": float(p.cost_basis_native),
            "trade_cost_native": float(cost), "difference_native": float(delta),
            "tolerance_native": float(tolerance), "currency": currency,
            "cost_unit_verified": currency_key(currency) == currency_key(p.currency),
        }
    return result


def mask_cost_under_review(payload: dict, review: dict | None) -> dict:
    """Keep valuation visible; never return conflicting costs/profits as facts."""
    if review and review["status"] == "not_comparable":
        review = {**review, "message": review.get("message") or UNKNOWN_MESSAGE}
    payload["cost_reconciliation"] = review
    if review and (review["status"] != "ok" or not review.get("cost_unit_verified", True)):
        for field in ("average_cost", "cost_basis", "cost_basis_native", "cost_basis_base",
                      "unrealized_pnl", "unrealized_pnl_native", "unrealized_pnl_base",
                      "pnl_price_effect_base", "pnl_fx_effect_base"):
            payload[field] = None
    return payload
