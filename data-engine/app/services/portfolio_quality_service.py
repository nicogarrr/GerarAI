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
    snapshots = list(db.scalars(select(PortfolioDailySnapshot).where(
        PortfolioDailySnapshot.portfolio_id == portfolio.id,
    ).order_by(PortfolioDailySnapshot.snapshot_date)))
    missing_cost = sum(1 for p in positions if p.quantity != 0 and (
        p.average_cost <= 0 or p.cost_basis_base is None or p.cost_basis_base == 0
    ))
    pdates = sorted({p.as_of.isoformat() for p in positions})
    cdates = sorted({c.as_of.isoformat() for c in cash})
    complete = [s for s in snapshots if s.pricing_coverage == Decimal("1")]
    returns = [s for s in snapshots if s.daily_return is not None and s.cumulative_twr is not None and s.pricing_coverage == Decimal("1")]
    # Cadena TWR: la primera foto de la serie es la base (sin retorno por
    # definicion); cualquier foto posterior sin daily_return/cumulative_twr es
    # un eslabon roto y, por diseno, la cadena no se reinicia sola (ver
    # PortfolioSnapshotService). Una cadena rota es la causa observable de que
    # las bandas de Factores salgan SIN DATOS aun existiendo snapshots: se
    # diagnostica aqui con su primera fecha para no adivinarla en produccion.
    unlinked = [
        s for s in snapshots[1:]
        if s.daily_return is None or s.cumulative_twr is None
    ]
    twr_chain = {
        "status": (
            "no_snapshots" if not snapshots else "broken" if unlinked else "linked"
        ),
        "unlinked_snapshots": len(unlinked),
        "first_unlinked_date": unlinked[0].snapshot_date.isoformat() if unlinked else None,
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
    if snapshots and snapshots[-1].pricing_coverage != Decimal("1"):
        reasons.append("latest_snapshot_incomplete")
    if len(returns) < 2:
        reasons.append("insufficient_verified_returns")
    if unlinked:
        reasons.append("twr_chain_broken")
    return {
        "status": "incomplete" if reasons else "ok", "positions": len(positions),
        "missing_cost_positions": missing_cost, "cost_review_positions": cost_reviews, "cost_unverified_positions": cost_unverified, "position_dates": pdates, "cash_dates": cdates,
        "cash_native": cash_native,
        "position_sources": sorted({p.source for p in positions}),
        "cash_sources": sorted({c.source for c in cash}),
        "snapshots": len(snapshots), "complete_snapshots": len(complete),
        "return_observations": len(returns),
        "latest_snapshot_date": snapshots[-1].snapshot_date.isoformat() if snapshots else None,
        "latest_pricing_coverage": float(snapshots[-1].pricing_coverage) if snapshots else None,
        "twr_chain": twr_chain,
        "reasons": reasons,
    }
