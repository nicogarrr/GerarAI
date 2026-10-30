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
from types import SimpleNamespace
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


def resolve_cross_provider_events(
    records: Iterable[Any],
    uncertain: Iterable[UncertainDividendEvent] = (),
) -> tuple[list[Any], list[UncertainDividendEvent]]:
    """Segunda pasada, solo para proyecciones: Yahoo y FMP no se suman.

    Un grupo (empresa, ex_date, divisa) con filas de AL MENOS dos proveedores
    y AL MENOS dos importes distintos puede ser el mismo evento con importe
    ajustado (Yahoo) y declarado (FMP), o un ordinario + un especial: no hay
    forma de saberlo con los datos guardados, asi que se excluye entero y se
    devuelve como INCIERTO, igual que ``resolve_yahoo_events``. Un solo
    proveedor (p.ej. dos filas FMP el mismo dia) no se toca. Importes iguales
    entre proveedores no existen en BD (unique por empresa, fecha e importe).
    No borra ni actualiza nada.
    """
    kept: list[Any] = []
    groups: dict[tuple[Any, Any, Any], list[Any]] = defaultdict(list)
    for record in records:
        groups[(record.company_id, record.ex_date, record.currency)].append(record)
    out_uncertain = list(uncertain)
    for (company_id, ex_date, currency), rows in groups.items():
        sources = {r.source for r in rows}
        amounts = {Decimal(r.amount) for r in rows}
        if len(sources) >= 2 and len(amounts) >= 2:
            out_uncertain.append(
                UncertainDividendEvent(company_id, ex_date, currency, tuple(sorted(amounts)))
            )
        else:
            kept.extend(rows)
    return kept, out_uncertain


def amount_in_currency(
    amount: Decimal, record_currency: str | None, target_currency: str | None,
) -> Decimal | None:
    """Importe por accion en la divisa de la posicion, SIN tipo de cambio.

    Solo convierte unidades de la misma moneda (peniques GBX/GBp <-> libras
    GBP, ZAc <-> ZAR, ILA <-> ILS): la ingesta guarda los dividendos de Yahoo
    en peniques como ``GBX`` y el ledger conserva la divisa de la operacion
    (``GBp`` o ``GBP``). Monedas distintas devuelven None: nunca se mezclan.
    """
    from app.valuation.currency import normalize_currency

    major, divisor = normalize_currency(record_currency)
    target_major, target_divisor = normalize_currency(target_currency)
    if not major or major != target_major:
        return None
    return amount * Decimal(target_divisor) / Decimal(divisor)


def records_in_position_currency(records: Iterable[Any], position_currency: str | None) -> list[Any]:
    """Dividendos por accion expresados en la divisa de la posicion (sin FX).

    Las filas en la divisa exacta de la posicion se usan tal cual. Las de la
    misma moneda en otra unidad (GBX frente a GBp/GBP) se convierten. Si una
    misma fecha ex trae la moneda en dos unidades (FMP en GBP y Yahoo en GBX:
    el mismo dividendo de dos proveedores), solo cuenta una unidad -la exacta
    si existe- para no sumarlo dos veces. Otra moneda nunca entra.
    """
    by_date: dict[Any, dict[str, list[tuple[Any, Decimal]]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        per_share = amount_in_currency(record.amount, record.currency, position_currency)
        if per_share is not None:
            by_date[record.ex_date][record.currency].append((record, per_share))
    out: list[Any] = []
    for ex_date in sorted(by_date):
        groups = by_date[ex_date]
        unit = position_currency if position_currency in groups else sorted(groups)[0]
        for record, per_share in groups[unit]:
            out.append(SimpleNamespace(
                company_id=record.company_id, ex_date=record.ex_date, pay_date=record.pay_date,
                amount=per_share, currency=position_currency, source=record.source,
                fetched_at=getattr(record, "fetched_at", None),
            ))
    return out
