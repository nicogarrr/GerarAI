"""Base de ventas del DCF: últimos doce meses (TTM) o último ejercicio.

Owner (Nico, 4-nov-2026, «Sí»): el DCF partía siempre de las ventas del
último ejercicio (FY) aunque ya hubiera trimestres presentados después.
PLTR: FY2025 4.475 M$ con tres 10-Q de 2026 presentados (TTM 7.288 M$, SEC).

Regla general, para cualquier empresa:

- Si tras el cierre del ejercicio ancla del snapshot hay **al menos 2
  trimestres presentados**, la base es la suma de los 4 últimos trimestres
  consecutivos (fórmula única de :mod:`app.services.ttm_fundamentals`; el Q4
  que no se presenta en 10-Q se deriva como FY − 9 meses).
- Con 0 o 1 trimestre nuevo, la base sigue siendo el FY.
- Nunca se extrapola: un trimestre que falta, una unidad/divisa distinta del
  ancla, un TTM no positivo o una cadena que no enlaza con el ejercicio ancla
  dejan la base en el FY, con el motivo en la traza.
- Point-in-time: con corte ``as_of`` solo cuentan los hechos presentados
  (``filed``) hasta esa fecha, igual que el snapshot.

Solo cambia el nivel de ventas de partida. El margen FCF (ciclo medio o
FCF/ventas del snapshot) es un ratio y se aplica tal cual sobre la base
elegida; el crecimiento y el WACC no se tocan aquí.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models import FinancialFact
from app.services.ttm_fundamentals import trailing_twelve_months
from app.valuation.financial_snapshot import _available_at, _facts_for_metric

# Mínimo de trimestres presentados después del cierre del FY ancla.
MIN_NEW_QUARTERS = 2
# El trimestre más reciente debe caer dentro del ejercicio siguiente al ancla
# (52/53 semanas incluidas); si no, el ancla está desfasada y no se mezcla.
MAX_DAYS_AFTER_ANCHOR = 380

_END_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


@dataclass
class RevenueBase:
    value: float
    basis: str  # "ttm" | "annual"
    period_end: date | None
    reason: str
    new_quarters: int = 0
    quarters: list[dict[str, Any]] = field(default_factory=list)

    def trace(self) -> dict[str, Any]:
        return {
            "basis": self.basis,
            "value": self.value,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "new_quarters_after_fy": self.new_quarters,
            "reason": self.reason,
            "quarters": self.quarters,
        }


def _end(fact: FinancialFact | None) -> date | None:
    match = _END_RE.match(str(getattr(fact, "period", None) or ""))
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _annual(value: float, end: date | None, reason: str, new_quarters: int = 0) -> RevenueBase:
    return RevenueBase(value=value, basis="annual", period_end=end, reason=reason, new_quarters=new_quarters)


def resolve_revenue_base(
    db: Session | None,
    company_id: int,
    anchor: FinancialFact | None,
    annual_value: float,
    *,
    period_type: str | None,
    as_of: date | None = None,
) -> RevenueBase:
    """Ventas de partida del DCF (TTM si procede; si no, el valor anual)."""
    anchor_end = _end(anchor)
    if db is None or anchor is None or period_type != "FY" or anchor_end is None:
        return _annual(annual_value, anchor_end, "El ancla del snapshot no es un ejercicio fechado.")

    # Import diferido: ttm_service arrastra la ingesta, que a su vez importa
    # piezas de valoración (import circular al cargar el motor).
    from app.services.ttm_service import _best_by_period

    facts, _future, _unknown = _available_at(_facts_for_metric(db, company_id, "revenue"), as_of)
    quarters, annuals = _best_by_period(facts).get("revenue", ([], []))
    new = sorted(q.end for q in quarters if q.end > anchor_end)
    if len(new) < MIN_NEW_QUARTERS:
        return _annual(
            annual_value,
            anchor_end,
            f"{len(new)} trimestre(s) presentado(s) tras el FY: se mantiene el ejercicio.",
            len(new),
        )
    if (new[-1] - anchor_end).days > MAX_DAYS_AFTER_ANCHOR:
        return _annual(
            annual_value,
            anchor_end,
            "El último trimestre cae fuera del ejercicio siguiente al FY ancla.",
            len(new),
        )

    ttm = trailing_twelve_months("revenue", quarters, annuals)
    if ttm.basis != "TTM" or ttm.value is None or ttm.period_end is None:
        return _annual(
            annual_value,
            anchor_end,
            "No hay 4 trimestres consecutivos completos: se mantiene el ejercicio (sin extrapolar).",
            len(new),
        )
    if ttm.period_end != new[-1]:
        return _annual(annual_value, anchor_end, "El TTM no termina en el último trimestre.", len(new))
    if (ttm.unit or "") != (anchor.unit or ""):
        return _annual(
            annual_value,
            anchor_end,
            f"Unidad del TTM ({ttm.unit}) distinta de la del ejercicio ({anchor.unit}).",
            len(new),
        )
    chain_ends = [q.end for q in ttm.quarters]
    if not any(end <= anchor_end for end in chain_ends):
        return _annual(annual_value, anchor_end, "El TTM no enlaza con el FY ancla.", len(new))
    value = float(ttm.value)
    if value <= 0:
        return _annual(annual_value, anchor_end, "El TTM no es positivo.", len(new))
    return RevenueBase(
        value=value,
        basis="ttm",
        period_end=ttm.period_end,
        reason=(
            f"{len(new)} trimestres presentados tras el FY {anchor_end.isoformat()}: "
            "suma de los 4 últimos trimestres."
        ),
        new_quarters=len(new),
        quarters=[
            {
                "period_end": q.end.isoformat(),
                "value": float(q.value),
                "origin": q.origin,
            }
            for q in ttm.quarters
        ],
    )
