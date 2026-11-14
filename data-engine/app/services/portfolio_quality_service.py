"""Read-only portfolio diagnostics. No import, price refresh, backfill or model calls."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CashBalance, PortfolioDailySnapshot, Position
from app.services.portfolio_fx_service import PortfolioFXService


def portfolio_quality(db: Session) -> dict[str, Any]:
    portfolio = PortfolioFXService().portfolio(db)
    if portfolio is None:
        return {"status": "no_portfolio", "positions": 0, "missing_cost_positions": 0,
                "position_dates": [], "cash_dates": [], "position_sources": [], "cash_sources": [], "cash_native": {},
                "snapshots": 0, "complete_snapshots": 0, "return_observations": 0,
                "latest_snapshot_date": None, "latest_pricing_coverage": None,
                "twr_chain": {"status": "no_snapshots", "unlinked_snapshots": 0, "first_unlinked_date": None},
                "reasons": ["no_portfolio"]}
    positions = list(db.scalars(select(Position).where(Position.portfolio_id == portfolio.id)))
    cash = list(db.scalars(select(CashBalance)))
    # Only diagnostic columns, streamed: no historical valuation objects or
    # unrelated JSON payloads. Keep JSON truthiness in Python exactly as before.
    snapshot_rows = db.execute(select(
        PortfolioDailySnapshot.snapshot_date,
        PortfolioDailySnapshot.pricing_coverage,
        PortfolioDailySnapshot.daily_return,
        PortfolioDailySnapshot.cumulative_twr,
        PortfolioDailySnapshot.metadata_["twr_base_after_scope_change"],
    ).where(
        PortfolioDailySnapshot.portfolio_id == portfolio.id,
    ).order_by(PortfolioDailySnapshot.snapshot_date).execution_options(yield_per=500))
    snapshots = complete = returns = unlinked = 0
    first_unlinked_date = None
    latest_snapshot_date = latest_pricing_coverage = None
    for day, coverage, daily_return, cumulative_twr, scope_base in snapshot_rows:
        # The first snapshot is the base, never a broken link. A declared
        # base after a scope change is also exempt, regardless of coverage.
        if snapshots and (daily_return is None or cumulative_twr is None) and not scope_base:
            unlinked += 1
            if first_unlinked_date is None:
                first_unlinked_date = day.isoformat()
        snapshots += 1
        if coverage == Decimal("1"):
            complete += 1
            if daily_return is not None and cumulative_twr is not None:
                returns += 1
        latest_snapshot_date = day.isoformat()
        latest_pricing_coverage = coverage
    missing_cost = sum(1 for p in positions if p.quantity != 0 and (
        p.average_cost <= 0 or p.cost_basis_base is None or p.cost_basis_base == 0
    ))
    pdates = sorted({p.as_of.isoformat() for p in positions})
    cdates = sorted({c.as_of.isoformat() for c in cash})
    twr_chain = {
        "status": "no_snapshots" if not snapshots else "broken" if unlinked else "linked",
        "unlinked_snapshots": unlinked,
        "first_unlinked_date": first_unlinked_date,
    }
    cash_native: dict[str, float] = {}
    for row in cash:
        cash_native[row.currency] = cash_native.get(row.currency, 0.0) + float(row.balance)
    from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs

    cost_checks = reconcile_ibkr_costs(db, positions)
    cost_reviews = sum(r["status"] == "review_required" for r in cost_checks.values())
    cost_unverified = sum(r["status"] == "not_comparable" or not r.get("cost_unit_verified", True)
                          for r in cost_checks.values())
    reasons = []
    if cost_unverified:
        reasons.append("ibkr_cost_currency_unverified")
    if cost_reviews:
        reasons.append("ibkr_cost_mismatch")
    if missing_cost:
        reasons.append("missing_cost_basis")
    if len(set(pdates + cdates)) > 1:
        reasons.append("mixed_valuation_dates")
    if snapshots and latest_pricing_coverage != Decimal("1"):
        reasons.append("latest_snapshot_incomplete")
    if returns < 2:
        reasons.append("insufficient_verified_returns")
    if unlinked:
        reasons.append("twr_chain_broken")
    return {
        "status": "incomplete" if reasons else "ok", "positions": len(positions),
        "missing_cost_positions": missing_cost, "cost_review_positions": cost_reviews, "cost_unverified_positions": cost_unverified, "position_dates": pdates, "cash_dates": cdates,
        "cash_native": cash_native,
        "position_sources": sorted({p.source for p in positions}),
        "cash_sources": sorted({c.source for c in cash}),
        "snapshots": snapshots, "complete_snapshots": complete,
        "return_observations": returns,
        "latest_snapshot_date": latest_snapshot_date,
        "latest_pricing_coverage": float(latest_pricing_coverage) if snapshots else None,
        "twr_chain": twr_chain,
        "reasons": reasons,
    }
