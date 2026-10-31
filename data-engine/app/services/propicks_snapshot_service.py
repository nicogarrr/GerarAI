"""Monthly frozen ProPicks snapshot: the point-in-time record a future
backtest needs. Written once per tenant and month, never updated.

Stores every company that passes the funnel with its score, the metrics the
funnel used and the latest stored price with its date. Prices that are
missing stay None. A snapshot with no passing company is not stored: an empty
month is not evidence, and it would block the real one."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Company, MarketPrice
from app.models.propick_snapshot import PropickSnapshot
from app.services.propicks_funnel_service import FUNNEL_VERSION, run_funnel


def freeze_monthly_snapshot(db: Session, *, now: datetime | None = None) -> PropickSnapshot | None:
    now = now or datetime.now(UTC)
    month = now.strftime("%Y-%m")
    existing = db.scalar(select(PropickSnapshot).where(PropickSnapshot.month == month))
    if existing is not None:
        return existing  # immutable: the first freeze of the month wins
    results, stats = run_funnel(db, top_n=100)
    passed = [r for r in results if r.passed and r.score is not None]
    if not passed:
        return None
    ids = [r.company_id for r in passed]
    companies = {c.id: c for c in db.scalars(select(Company).where(Company.id.in_(ids))).all()}
    # Solo el ultimo cierre con dato por empresa: recorrer toda la historia
    # (~100 empresas x todos sus cierres) para descartar todo menos uno por
    # empresa es un orden de magnitud mas filas de las necesarias.
    latest = (
        select(
            MarketPrice.company_id.label("company_id"),
            MarketPrice.close.label("close"),
            MarketPrice.date.label("date"),
            func.row_number()
            .over(
                partition_by=MarketPrice.company_id,
                order_by=(MarketPrice.date.desc(), MarketPrice.id.desc()),
            )
            .label("rn"),
        )
        .where(MarketPrice.company_id.in_(ids), MarketPrice.close.isnot(None))
        .subquery()
    )
    prices = {
        row.company_id: row
        for row in db.execute(
            select(latest.c.company_id, latest.c.close, latest.c.date).where(latest.c.rn == 1)
        )
    }
    picks = []
    for r in sorted(passed, key=lambda x: (-(x.score or 0.0), x.company_id)):
        c = companies.get(r.company_id)
        if c is None:
            continue
        p = prices.get(r.company_id)
        picks.append(
            {
                "ticker": c.ticker,
                "name": c.name,
                "currency": c.currency,
                "score": r.score,
                "metrics": {k: v for k, v in r.metrics.items() if k != "rank"},
                "price": float(p.close) if p is not None else None,
                "price_date": p.date.isoformat() if p is not None else None,
            }
        )
    row = PropickSnapshot(
        month=month,
        as_of=now,
        funnel_version=FUNNEL_VERSION,
        universe_size=stats["universe_size"],
        passed_count=stats["passed_count"],
        payload={"params": stats["params"], "picks": picks},
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Otro proceso congelo el mes a la vez: gana el primero y no se sobrescribe.
        db.rollback()
        winner = db.scalar(select(PropickSnapshot).where(PropickSnapshot.month == month))
        if winner is None:
            raise
        return winner
    db.refresh(row)
    return row
