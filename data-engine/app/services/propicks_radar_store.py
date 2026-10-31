"""Persist public-price snapshots, scoped private overlays are applied elsewhere."""
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, ProPicksRadarSnapshot
from app.services.propicks_dca_radar import signal_change

FORMULA_VERSION = 'nico-v2'
_PUBLIC_KEYS = frozenset({'status', 'reason', 'formula_version', 'price_verified', 'price_date',
                          'source', 'current', 'confirmed', 'clear_price_signal',
                          'daily_close_drawdown', 'drawdown_basis'})


def save_snapshot(db: Session, company_id: int, payload: dict, *, now: datetime) -> None:
    """Save snapshot and checkpoint atomically; caller owns the exclusive scan lease.

    Reject arbitrary/private keys rather than silently sharing tenant quality.
    Same-day retries replace the same snapshot and do not inflate coverage.
    """
    if set(payload) - _PUBLIC_KEYS:
        raise ValueError('only public price signal fields may be persisted')
    if payload.get('status') not in ('ok', 'invalid'):
        raise ValueError('invalid snapshot status')
    if payload.get('formula_version', FORMULA_VERSION) != FORMULA_VERSION:
        raise ValueError('formula mismatch')
    if db.get(Company, company_id) is None:
        raise ValueError('unknown company')
    scan_date = now.date()
    snapshot = db.scalar(select(ProPicksRadarSnapshot).where(
        ProPicksRadarSnapshot.company_id == company_id,
        ProPicksRadarSnapshot.scan_date == scan_date,
        ProPicksRadarSnapshot.formula_version == FORMULA_VERSION))
    if snapshot is None:
        snapshot = ProPicksRadarSnapshot(company_id=company_id, scan_date=scan_date,
                                         formula_version=FORMULA_VERSION)
        db.add(snapshot)
    snapshot.evaluated_at = now
    snapshot.status = payload['status']
    snapshot.payload = {**payload, 'formula_version': FORMULA_VERSION}
    db.commit()


def scan_cursor(db: Session, scan_date: date) -> tuple[int, int]:
    """Punto de reanudacion del barrido: (ultima empresa guardada, guardadas).

    Se DERIVA de los snapshots del dia filtrados por FORMULA_VERSION: la
    tabla legada de cursores no tenia version de formula y un cambio de
    formula a mitad de dia heredaba el progreso de la formula anterior
    (bug de prod del 31-oct-2026: v2 se habria saltado 1000 empresas).
    Derivandolo, el cursor no puede desviarse de lo guardado y cada formula
    reanuda solo su propio barrido. ``saved_count`` no se infla en
    reintentos del mismo dia porque el guardado reemplaza el snapshot.
    """
    after_id, saved = db.execute(
        select(
            func.coalesce(func.max(ProPicksRadarSnapshot.company_id), 0),
            func.count(),
        ).where(
            ProPicksRadarSnapshot.scan_date == scan_date,
            ProPicksRadarSnapshot.formula_version == FORMULA_VERSION,
        )
    ).one()
    return (int(after_id), int(saved))


def latest_public_signals(db: Session, *, as_of: date, company_limit: int = 1000) -> list[dict]:
    """Read at most two snapshots per company; never fetch full price histories."""
    ids = db.scalars(
        select(ProPicksRadarSnapshot.company_id)
        .where(ProPicksRadarSnapshot.scan_date <= as_of,
               ProPicksRadarSnapshot.formula_version == FORMULA_VERSION)
        .group_by(ProPicksRadarSnapshot.company_id)
        .order_by(ProPicksRadarSnapshot.company_id)
        .limit(min(company_limit, 1000))
    ).all()
    ranked = select(
        ProPicksRadarSnapshot.id,
        func.row_number().over(
            partition_by=ProPicksRadarSnapshot.company_id,
            order_by=ProPicksRadarSnapshot.scan_date.desc(),
        ).label('rank'),
    ).where(ProPicksRadarSnapshot.company_id.in_(ids),
            ProPicksRadarSnapshot.scan_date <= as_of,
            ProPicksRadarSnapshot.formula_version == FORMULA_VERSION).subquery()
    snapshots = db.scalars(select(ProPicksRadarSnapshot).join(
        ranked, ranked.c.id == ProPicksRadarSnapshot.id,
    ).where(ranked.c.rank <= 2).order_by(
        ProPicksRadarSnapshot.company_id, ProPicksRadarSnapshot.scan_date.desc())).all()
    grouped: dict[int, list[ProPicksRadarSnapshot]] = {}
    for snapshot in snapshots:
        grouped.setdefault(snapshot.company_id, []).append(snapshot)
    result = []
    for company_id, rows in grouped.items():
        current = rows[0]
        previous = rows[1].payload if len(rows) > 1 else None
        result.append({'company_id': company_id, 'scan_date': current.scan_date.isoformat(),
                       'payload': current.payload, 'change': signal_change(current.payload, previous)})
    return result
