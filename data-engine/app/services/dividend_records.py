"""Lectura de DividendRecord sin doble conteo por reajuste de splits.

Yahoo chart da importes AJUSTADOS por splits posteriores (AAPL 2020: 0.1925
ajustado vs 0.77 declarado) y el dedupe de ingesta es (empresa, ex_date,
amount): tras un split coexisten la fila vieja y la reajustada.

Pero dos filas de Yahoo con la misma fecha ex NO son siempre un reajuste: un
dividendo ordinario y uno especial pueden caer el mismo dia con distinto
timestamp, y distintos importes pueden ser legitimos. Solo se consolida un
grupo (empresa, ex_date, divisa, fuente Yahoo) cuando hay EVIDENCIA: cada fila
mas antigua / la mas reciente coincide (1 %) con el producto acumulado de splits
ingeridos con effective_date posterior a la ex_date. Sin esa evidencia el grupo
es INCIERTO: se excluye por completo de totales y se devuelve para senalarlo
(nunca se elige «la ultima» por defecto). No se borra ni actualiza ninguna fila.
Otras fuentes (FMP) no se tocan.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

YAHOO_SOURCE = "yahoo_finance"
_TOLERANCE = Decimal("0.01")

SplitRatios = Mapping[int, Sequence[tuple[date, Decimal]]]


@dataclass(frozen=True)
class UncertainDividendEvent:
    company_id: int
    ex_date: date
    currency: str
    amounts: tuple[Decimal, ...]


def split_ratios_for(db: Any, company_ids: Iterable[int]) -> dict[int, list[tuple[date, Decimal]]]:
    """Splits/reverse splits ingeridos (CorporateAction), ordenados por fecha."""
    from sqlalchemy import select

    from app.models.entities import CorporateAction

    ids = list(company_ids)
    out: dict[int, list[tuple[date, Decimal]]] = defaultdict(list)
    if not ids:
        return out
    rows = db.scalars(
        select(CorporateAction).where(
            CorporateAction.company_id.in_(ids),
            CorporateAction.action_type.in_(("split", "reverse_split")),
        )
    ).all()
    for row in rows:
        if row.ratio and row.ratio > 0:
            out[row.company_id].append((row.effective_date, Decimal(row.ratio)))
    for items in out.values():
        items.sort(key=lambda item: item[0])
    return out


def _explained_by_splits(
    older: Decimal, latest: Decimal, ex_date: date, splits: Sequence[tuple[date, Decimal]]
) -> bool:
    if latest <= 0 or older <= 0:
        return False
    observed = older / latest
    cumulative = Decimal(1)
    for effective, ratio in splits:
        if effective <= ex_date:
            continue
        cumulative *= ratio
        if abs(observed - cumulative) <= _TOLERANCE * cumulative:
            return True
    return False


def _stamp(record: Any) -> tuple[datetime, int]:
    fetched = record.fetched_at or datetime.min
    return (fetched.replace(tzinfo=None), record.id or 0)


def resolve_yahoo_events(
    records: Iterable[Any], split_ratios: SplitRatios | None = None
) -> tuple[list[Any], list[UncertainDividendEvent]]:
    """(filas utilizables, eventos inciertos excluidos)."""
    splits_by_company = split_ratios or {}
    kept: list[Any] = []
    groups: dict[tuple[Any, Any, Any], list[Any]] = defaultdict(list)
    for record in records:
        if record.source != YAHOO_SOURCE:
            kept.append(record)
        else:
            groups[(record.company_id, record.ex_date, record.currency)].append(record)
    uncertain: list[UncertainDividendEvent] = []
    for (company_id, ex_date, currency), rows in groups.items():
        if len(rows) == 1:
            kept.append(rows[0])
            continue
        ordered = sorted(rows, key=_stamp)
        latest = ordered[-1]
        splits = splits_by_company.get(company_id, ())
        if all(
            row.amount == latest.amount
            or _explained_by_splits(Decimal(row.amount), Decimal(latest.amount), ex_date, splits)
            for row in ordered[:-1]
        ):
            kept.append(latest)
        else:
            uncertain.append(
                UncertainDividendEvent(
                    company_id, ex_date, currency, tuple(sorted(Decimal(r.amount) for r in rows))
                )
            )
    return kept, uncertain
