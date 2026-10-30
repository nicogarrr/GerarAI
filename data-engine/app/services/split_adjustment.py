"""Ajuste por splits de ratios precio/por-accion (PER y derivados).

El precio es HOY pero el EPS es del cierre de su ejercicio: si entre ambos
hubo un split, `precio / eps_reportado` infla el PER por el factor del
split (caso real: un 4:1 cuadruplica el PER aparente). El EPS se expresa
en acciones actuales dividiendo por el factor acumulado de los splits
posteriores al cierre de SU periodo, espejo del ajuste de recuentos de
acciones de long_term_model_service (que multiplica).

Sin splits registrados en BD no se ajusta nada (factor 1): un split que
falte en BD se detecta en las series de acciones (salto inexplicable ->
N/D), nunca se adivina aqui.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CorporateAction


def split_events_by_company(
    db: Session, company_ids: list[int]
) -> dict[int, list[tuple[date, Decimal]]]:
    """Splits/reverse splits por compania, ordenados por fecha efectiva."""
    if not company_ids:
        return {}
    rows = db.scalars(
        select(CorporateAction)
        .where(
            CorporateAction.company_id.in_(company_ids),
            CorporateAction.action_type.in_(["split", "reverse_split"]),
        )
        .order_by(CorporateAction.effective_date)
    ).all()
    out: dict[int, list[tuple[date, Decimal]]] = {}
    for row in rows:
        if row.effective_date is None or row.ratio is None:
            continue
        out.setdefault(row.company_id, []).append(
            (row.effective_date, Decimal(str(row.ratio)))
        )
    return out


def cumulative_split_factor_after(
    events: list[tuple[date, Decimal]], ref_date: date | None
) -> Decimal:
    """Factor acumulado de los splits con fecha efectiva POSTERIOR a
    `ref_date` (ratio = acciones despues / antes; reverse < 1). Sin fecha
    de referencia parseable, factor 1: ajustar a ciegas seria inventar."""
    if ref_date is None:
        return Decimal(1)
    factor = Decimal(1)
    for effective, ratio in events:
        if effective > ref_date:
            factor *= ratio
    return factor


def period_end_date(period: str | None) -> date | None:
    """`"<end>:FY"` / `"<end>:DEI"` -> date; lo no parseable es None."""
    try:
        return date.fromisoformat((period or "").split(":")[0])
    except ValueError:
        return None


def fact_split_factor(
    events: list[tuple[date, Decimal]],
    *,
    period: str | None,
    filed: date | None,
    cutoff: date | None = None,
) -> Decimal:
    """Factor de los splits que un hecho NO recoge todavia (regla unica).

    Cuenta los splits efectivos despues del cierre del periodo y tambien
    despues de la publicacion (``filed``): un 10-K publicado tras el split ya
    viene reexpresado (ASC 260), y ajustarlo otra vez lo duplicaria. Un
    recuento de portada (``:DEI``) es una foto a SU fecha: no se reexpresa, asi
    que ahi solo cuenta esa fecha. Con ``cutoff`` (fecha del precio o del
    as_of) solo entran splits con fecha <= cutoff: un split futuro respecto al
    precio no cambia ese precio.
    """
    ref = period_end_date(period)
    if ref is None:
        return Decimal(1)
    point_in_time = (period or "").upper().endswith(":DEI")
    if filed is not None and filed > ref and not point_in_time:
        ref = filed
    if cutoff is not None:
        events = [event for event in events if event[0] <= cutoff]
    return cumulative_split_factor_after(events, ref)


def split_factor_for_fact(
    db: Session,
    company_id: int,
    *,
    period: str | None,
    filed: date | None,
    cutoff: date,
) -> Decimal:
    """``fact_split_factor`` leyendo los splits de la compania en BD."""
    return fact_split_factor(
        split_events_by_company(db, [company_id]).get(company_id, []),
        period=period,
        filed=filed,
        cutoff=cutoff,
    )
