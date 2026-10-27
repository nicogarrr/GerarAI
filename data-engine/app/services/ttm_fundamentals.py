"""TTM (últimos doce meses) a partir de trimestres y ejercicios guardados.

Funciones puras, sin base de datos, para que la fórmula se pueda auditar con
cifras reales en tests (ver tests/test_ttm_fundamentals.py, Apple AAPL).

Fórmula (convención de mercado; Investopedia, «Trailing 12 Months (TTM)»):

- Flujos (ventas, beneficio, flujo operativo, capex, BPA, D&A, intereses...):
  suma de los 4 últimos trimestres fiscales CONSECUTIVOS.
- Balance (caja, deuda, patrimonio, acciones, activos...): el último dato
  (trimestre o ejercicio, el más reciente).
- Q4 casi nunca se presenta en un 10-Q (va dentro del 10-K): se deriva como
  Q4 = FY − (Q1 + Q2 + Q3), es decir FY − acumulado de 9 meses. INFERIDO.
- Flujos que el 10-Q solo trae acumulados (el estado de flujos de efectivo
  suele venir en 3, 6 y 9 meses): trimestre = YTD(t) − YTD(t−1) del mismo
  ejercicio (mismo ``start``). INFERIDO.

Nunca se inventa: si no hay 4 trimestres contiguos (de 70 a 110 días entre
cierres, para cubrir años de 52/53 semanas) con la misma unidad, se usa el
último ejercicio (FY) etiquetado como tal; sin ejercicio, SIN_DATOS.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

Basis = Literal["TTM", "FY", "Q", "SIN_DATOS"]
Provenance = Literal["OFICIAL", "INFERIDO", "SIN_DATOS"]

# Partidas de flujo que se suman en el TTM.
FLOW_METRICS: tuple[str, ...] = (
    "revenue",
    "gross_profit",
    "operating_income",
    "income_before_tax",
    "income_tax_expense",
    "interest_expense",
    "net_income",
    "eps_diluted",
    "operating_cash_flow",
    "capital_expenditure",
    "depreciation_amortization",
    "stock_based_compensation",
    "dividends_paid",
    "common_stock_repurchased",
    "common_stock_issued",
    "finance_lease_additions",
)
# Partidas que NO se derivan restando acumulados: el BPA y las acciones medias
# no son aditivos (cambia el denominador entre periodos).
NON_ADDITIVE_FLOWS: frozenset[str] = frozenset({"eps_diluted", "shares_diluted"})
# Instantáneos de balance (y la media ponderada de acciones, que se toma del
# último periodo: sumarla no tiene sentido).
POINT_METRICS: tuple[str, ...] = (
    "cash_and_equivalents",
    "total_debt",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "shares_outstanding",
    "shares_diluted",
    "goodwill",
    "intangible_assets",
    "operating_lease_liabilities",
)

QUARTER_MIN_DAYS = 70
QUARTER_MAX_DAYS = 110

LABELS: dict[str, str] = {
    "TTM": "TTM (últimos 4 trimestres)",
    "FY": "FY (último ejercicio)",
    "Q": "Último trimestre",
    "SIN_DATOS": "Sin datos",
}

EPS_NOTE = (
    "Aproximado: el BPA no es exactamente aditivo entre trimestres "
    "(cambia el número medio de acciones)."
)


@dataclass(frozen=True)
class PeriodValue:
    """Un dato guardado: trimestre (3 meses), acumulado YTD, ejercicio o
    instantáneo de balance (sin ``start``)."""

    end: date
    value: Decimal
    start: date | None = None
    unit: str = "USD"
    reported: bool = True
    fact_id: int | None = None


@dataclass(frozen=True)
class TtmQuarter:
    end: date
    value: Decimal
    reported: bool
    origin: str  # "10-Q" | "YTD" (acumulado restado) | "FY-9M" (Q4 derivado)
    fact_ids: tuple[int, ...] = ()


@dataclass
class TtmValue:
    metric: str
    value: Decimal | None
    basis: Basis
    provenance: Provenance
    period_end: date | None = None
    unit: str | None = None
    quarters: list[TtmQuarter] = field(default_factory=list)
    note: str | None = None
    fact_ids: list[int] = field(default_factory=list)

    @property
    def label(self) -> str:
        return LABELS[self.basis]


def _days(later: date, earlier: date) -> int:
    return (later - earlier).days


def _is_quarter_gap(later: date, earlier: date) -> bool:
    return QUARTER_MIN_DAYS <= _days(later, earlier) <= QUARTER_MAX_DAYS


def _span(row: PeriodValue) -> int | None:
    return _days(row.end, row.start) if row.start is not None else None


def _is_quarter(row: PeriodValue) -> bool:
    span = _span(row)
    return span is not None and QUARTER_MIN_DAYS <= span <= QUARTER_MAX_DAYS


def _ids(*rows: PeriodValue) -> tuple[int, ...]:
    return tuple(r.fact_id for r in rows if r.fact_id is not None)


def derive_quarters_from_ytd(rows: Iterable[PeriodValue]) -> list[PeriodValue]:
    """Trimestres de 3 meses a partir de 10-Q (presentados o acumulados).

    Devuelve un ``PeriodValue`` por cierre trimestral: el de 3 meses si se
    presentó (``reported=True``) o, si solo hay acumulados, la diferencia
    YTD(t) − YTD(t−1) del mismo ejercicio (``reported=False``). El acumulado
    anterior puede ser el primer trimestre (3 meses con el mismo ``start``).
    Un acumulado sin su anterior no produce nada.
    """
    flows = [r for r in rows if r.start is not None]
    quarters: dict[date, PeriodValue] = {}
    for row in flows:
        if _is_quarter(row):
            current = quarters.get(row.end)
            if current is None or not current.reported:
                quarters[row.end] = row
    cumulative: dict[tuple[date, date], PeriodValue] = {}
    for row in flows:
        if row.start is not None:
            cumulative.setdefault((row.start, row.end), row)
    for row in sorted(flows, key=lambda r: r.end):
        if row.end in quarters or row.start is None or _is_quarter(row):
            continue
        span = _span(row)
        if span is None or span <= QUARTER_MAX_DAYS:
            continue
        previous = [
            prev
            for (start, end), prev in cumulative.items()
            if start == row.start and _is_quarter_gap(row.end, end) and prev.unit == row.unit
        ]
        if len(previous) != 1:
            continue
        prev = previous[0]
        quarters[row.end] = PeriodValue(
            start=prev.end + timedelta(days=1),
            end=row.end,
            value=row.value - prev.value,
            unit=row.unit,
            reported=False,
            fact_id=None,
        )
    return sorted(quarters.values(), key=lambda r: r.end)


def _quarter_series(
    quarters: Sequence[PeriodValue], annuals: Sequence[PeriodValue]
) -> tuple[dict[date, TtmQuarter], dict[date, str]]:
    """Trimestres guardados + Q4 derivados (FY − Q1 − Q2 − Q3), con la
    unidad de cada cierre."""
    series: dict[date, TtmQuarter] = {}
    units: dict[date, str] = {}
    for q in quarters:
        if q.end in series and series[q.end].reported:
            continue
        series[q.end] = TtmQuarter(
            end=q.end,
            value=q.value,
            reported=q.reported,
            origin="10-Q" if q.reported else "YTD",
            fact_ids=_ids(q),
        )
        units[q.end] = q.unit
    by_end = {q.end: q for q in quarters}
    for fy in annuals:
        if fy.end in series:
            continue
        ordered = sorted((q for q in by_end.values() if q.end < fy.end), key=lambda q: q.end)
        if len(ordered) < 3:
            continue
        q1, q2, q3 = ordered[-3:]
        if not (
            _is_quarter_gap(fy.end, q3.end)
            and _is_quarter_gap(q3.end, q2.end)
            and _is_quarter_gap(q2.end, q1.end)
        ):
            continue
        if fy.start is not None and q1.start is not None and abs(_days(q1.start, fy.start)) > 7:
            # Q1 debe abrir el mismo ejercicio que el FY.
            continue
        if not all(q.unit == fy.unit for q in (q1, q2, q3)):
            continue
        series[fy.end] = TtmQuarter(
            end=fy.end,
            value=fy.value - (q1.value + q2.value + q3.value),
            reported=False,
            origin="FY-9M",
            fact_ids=_ids(fy, q1, q2, q3),
        )
        units[fy.end] = fy.unit
    return series, units


def _fallback_fy(metric: str, annuals: Sequence[PeriodValue], note: str | None = None) -> TtmValue:
    if not annuals:
        return TtmValue(metric=metric, value=None, basis="SIN_DATOS", provenance="SIN_DATOS", note=note)
    fy = max(annuals, key=lambda r: r.end)
    return TtmValue(
        metric=metric,
        value=fy.value,
        basis="FY",
        provenance="OFICIAL" if fy.reported else "INFERIDO",
        period_end=fy.end,
        unit=fy.unit,
        note=note,
        fact_ids=list(_ids(fy)),
    )


def trailing_twelve_months(
    metric: str,
    quarters: Sequence[PeriodValue],
    annuals: Sequence[PeriodValue],
) -> TtmValue:
    """TTM de una partida de flujo, o el último FY etiquetado si no hay 4
    trimestres contiguos. ``quarters`` son trimestres de 3 meses (presentados
    o ya derivados de acumulados con :func:`derive_quarters_from_ytd`)."""
    quarters = [q for q in quarters if q.start is None or _is_quarter(q)]
    annuals = list(annuals)
    latest_fy_end = max((a.end for a in annuals), default=None)
    latest_q_end = max((q.end for q in quarters), default=None)
    if latest_q_end is None or (latest_fy_end is not None and latest_fy_end >= latest_q_end):
        return _fallback_fy(metric, annuals)

    series, units = _quarter_series(quarters, annuals)
    chain: list[TtmQuarter] = [series[latest_q_end]]
    while len(chain) < 4:
        current = chain[-1].end
        candidates = [end for end in series if end < current and _is_quarter_gap(current, end)]
        if len(candidates) != 1:
            break
        chain.append(series[candidates[0]])
    chain_units = {units.get(q.end) for q in chain}
    if len(chain) < 4 or len(chain_units) != 1:
        return _fallback_fy(
            metric,
            annuals,
            note="No hay 4 trimestres consecutivos con la misma unidad.",
        )
    chain.reverse()
    total = sum((q.value for q in chain), Decimal("0"))
    inferred = any(not q.reported for q in chain)
    note = EPS_NOTE if metric == "eps_diluted" and inferred else None
    fact_ids = sorted({fid for q in chain for fid in q.fact_ids})
    return TtmValue(
        metric=metric,
        value=total,
        basis="TTM",
        provenance="INFERIDO" if inferred else "OFICIAL",
        period_end=chain[-1].end,
        unit=chain_units.pop(),
        quarters=chain,
        note=note,
        fact_ids=fact_ids,
    )


def latest_point(
    metric: str,
    quarters: Sequence[PeriodValue],
    annuals: Sequence[PeriodValue],
) -> TtmValue:
    """Balance: el dato más reciente (trimestre o ejercicio)."""
    latest_fy = max(annuals, key=lambda r: r.end, default=None)
    latest_q = max(quarters, key=lambda r: r.end, default=None)
    if latest_fy is None and latest_q is None:
        return TtmValue(metric=metric, value=None, basis="SIN_DATOS", provenance="SIN_DATOS")
    # A igual fecha manda el FY (cifra auditada del 10-K).
    basis: Basis
    if latest_q is None or (latest_fy is not None and latest_fy.end >= latest_q.end):
        assert latest_fy is not None
        row, basis = latest_fy, "FY"
    else:
        row, basis = latest_q, "Q"
    return TtmValue(
        metric=metric,
        value=row.value,
        basis=basis,
        provenance="OFICIAL" if row.reported else "INFERIDO",
        period_end=row.end,
        unit=row.unit,
        fact_ids=list(_ids(row)),
    )


def combine_ttm(
    metric: str, left: TtmValue, right: TtmValue, *, op: Literal["add", "sub"]
) -> TtmValue:
    """Combina dos valores (p. ej. FCF = flujo operativo + capex negativo, o
    deuda neta = deuda − caja) solo si son del mismo periodo y unidad."""
    if (
        left.value is None
        or right.value is None
        or left.period_end != right.period_end
        or left.unit != right.unit
    ):
        return TtmValue(
            metric=metric,
            value=None,
            basis="SIN_DATOS",
            provenance="SIN_DATOS",
            note="Faltan componentes del mismo periodo.",
        )
    value = left.value + right.value if op == "add" else left.value - right.value
    basis: Basis = left.basis if left.basis == right.basis else "Q"
    if {left.basis, right.basis} == {"TTM"}:
        basis = "TTM"
    inferred = "INFERIDO" in (left.provenance, right.provenance)
    return TtmValue(
        metric=metric,
        value=value,
        basis=basis,
        provenance="INFERIDO" if inferred else "OFICIAL",
        period_end=left.period_end,
        unit=left.unit,
        quarters=[],
        fact_ids=sorted(set(left.fact_ids) | set(right.fact_ids)),
    )
