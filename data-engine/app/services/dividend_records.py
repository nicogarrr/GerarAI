"""Lectura de DividendRecord con eventos Yahoo ambiguos marcados como INCIERTOS.

Yahoo chart da importes AJUSTADOS por splits posteriores (AAPL 2020: 0.1925
ajustado vs 0.77 declarado) y el dedupe de ingesta es (empresa, ex_date,
amount): tras un split pueden coexistir la fila vieja y la reajustada. Pero dos
filas Yahoo con la misma fecha ex y distinto importe tambien pueden ser un
ordinario + un especial (o una subcuenta): un ratio de split coincidente solo
indica un POSIBLE reajuste, no la identidad del evento, y la BD no guarda
timestamp/version/evento del proveedor.

Regla: grupo (empresa, ex_date, divisa, fuente Yahoo) con importes distintos =>
INCIERTO: se excluye por completo de totales y se devuelve para senalarlo. Nunca
se consolida ni se elige «la ultima». Importes iguales no son ambiguos (se
conserva una fila). Otras fuentes (FMP) no se tocan. No se borra ni actualiza
nada.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

YAHOO_SOURCE = "yahoo_finance"


@dataclass(frozen=True)
class UncertainDividendEvent:
    company_id: int
    ex_date: date
    currency: str
    amounts: tuple[Decimal, ...]


def _stamp(record: Any) -> tuple[datetime, int]:
    fetched = record.fetched_at or datetime.min
    return (fetched.replace(tzinfo=None), record.id or 0)


def resolve_yahoo_events(
    records: Iterable[Any],
) -> tuple[list[Any], list[UncertainDividendEvent]]:
    """(filas utilizables, eventos inciertos excluidos)."""
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
        if len({Decimal(r.amount) for r in rows}) == 1:
            kept.append(max(rows, key=_stamp))
        else:
            uncertain.append(
                UncertainDividendEvent(
                    company_id, ex_date, currency, tuple(sorted(Decimal(r.amount) for r in rows))
                )
            )
    return kept, uncertain
