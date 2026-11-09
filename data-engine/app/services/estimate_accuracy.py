"""Acierto medido de cada fuente de estimación: congelada antes del resultado, frente al dato real.

- :func:`freeze_consensus` guarda cada celda publicada del consenso propio como
  ``estimate.<métrica>.<periodo>`` (``method='derive'``) SOLO cuando cambia: el
  historial de revisiones de ``declared_input_values`` es la foto congelada, con
  su fecha (``as_of``), su fuente y su fórmula.
- :func:`cases` cruza cada estimación con el dato real presentado (SEC/ESEF) del mismo
  periodo, usando la ÚLTIMA revisión emitida antes del cierre del periodo. La guía de
  la empresa entra como fuente «guia» (incluida la reconstruida de 8-K antiguos,
  :mod:`guidance_backfill`), las celdas congeladas con su fuente, y los analistas
  citados por firma.
- :func:`summarize` da, por fuente (o firma) y horizonte: casos, error absoluto
  mediano, sesgo mediano (real ÷ estimación − 1) y % de casos dentro del rango
  bajo–alto. :func:`measured_errors` alimenta la confianza de ``own_consensus``.

Error = real ÷ estimación − 1 (positivo: el dato superó la estimación). Puro salvo las
funciones que leen o escriben la BD.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.services.own_consensus import (
    FACT_METRIC,
    METRICS,
    Actual,
    GuidanceRow,
    actuals_from_facts,
    fy_end_month,
    horizon_of,
    label_offset_of,
    period_end,
)

ACCURACY_VERSION = "acierto_estimaciones v1"
# Solo se aparta un caso cuando la cifra real y la estimada no pueden estar en la misma unidad:
# una está ~1.000 o ~1.000.000 de veces la otra (miles frente a unidades, millones frente a
# unidades). Todo lo demás es un fallo (o un acierto) de previsión y cuenta, aunque sea grande o
# cambie de signo (una pérdida cuando se esperaba beneficio es el peor fallo, no una lectura
# inverosímil). Lo apartado se ve en el caso, con su motivo, y se cuenta en el resumen.
SCALE_FACTORS = (1e3, 1e6)
SCALE_TOLERANCE_DECADES = 0.5  # ±0,5 órdenes de magnitud alrededor de ×1.000 o ×1.000.000
# Error extremo: se marca (visible), pero cuenta. En los ingresos (no cambian de signo ni se
# multiplican por tres en un año frente a la guía) un real a más de 3 veces, o menos de un tercio,
# de la estimación es una lectura errónea: se aparta con su motivo (y se cuenta en el resumen).
EXTREME_RATIO = 3.0
STABLE_METRICS = frozenset({"revenue"})


def scale_mismatch(actual: float, estimate: float) -> str | None:
    """Motivo si la cifra real y la estimada parecen estar en unidades distintas (×1.000, ×1.000.000)."""
    if not actual or not estimate:
        return None
    gap = abs(math.log10(abs(actual / estimate)))
    for factor in SCALE_FACTORS:
        if abs(gap - math.log10(factor)) <= SCALE_TOLERANCE_DECADES:
            return (f"escala_distinta: el dato real es {actual / estimate:,.0f} veces la estimación "
                    f"(≈×{factor:,.0f}: miles o millones frente a unidades)").replace(",", ".")
    return None


@dataclass(frozen=True)
class Estimate:
    source: str  # guia | analista:<firma> | <fuente del consenso propio>
    metric: str
    period: str
    low: float | None
    mid: float
    high: float | None
    as_of: date
    url: str | None = None


def cases(estimates: Sequence[Estimate], actuals: Mapping[str, Mapping[str, Actual]]) -> list[dict[str, Any]]:
    """Un caso por (fuente, métrica, periodo): la última estimación anterior al cierre."""
    fy_month: dict[str, int] = {m: fy_end_month([a.end for k, a in acts.items() if k.startswith("fy")])
                                for m, acts in actuals.items()}
    offset: dict[str, int] = {m: label_offset_of(acts) for m, acts in actuals.items()}
    last: dict[tuple[str, str, str], Estimate] = {}
    for e in sorted(estimates, key=lambda e: e.as_of):
        acts = actuals.get(e.metric)
        if not acts:
            continue
        try:
            end = period_end(e.period, fy_month.get(e.metric, 12), offset.get(e.metric, 0))
        except (ValueError, IndexError):
            continue
        if e.as_of < end:
            last[(e.source, e.metric, e.period)] = e
    out: list[dict[str, Any]] = []
    for (source, metric, period), e in sorted(last.items()):
        real = actuals[metric].get(period)
        if real is None or not e.mid:
            continue
        end = period_end(period, fy_month.get(metric, 12), offset.get(metric, 0))
        ratio = real.value / e.mid
        excluded = scale_mismatch(real.value, e.mid)
        if not excluded and metric in STABLE_METRICS and not (1 / EXTREME_RATIO <= ratio <= EXTREME_RATIO):
            excluded = f"lectura_inverosímil: el dato real es {ratio:.2f} veces la estimación"
        flags = []
        if not excluded and ratio < 0:
            flags.append("signo_contrario: el dato real tiene el signo opuesto a la estimación")
        elif not excluded and (ratio == 0 or ratio > EXTREME_RATIO or ratio < 1 / EXTREME_RATIO):
            flags.append(f"error_extremo: el dato real es {ratio:.2f} veces la estimación")
        inside = None
        if e.low is not None and e.high is not None:
            inside = e.low <= real.value <= e.high
        out.append({"source": source, "metric": metric, "period": period, "as_of": e.as_of.isoformat(),
                    "horizon": horizon_of(end, e.as_of), "estimate": e.mid, "low": e.low, "high": e.high,
                    "actual": real.value, "actual_derived": real.derived, "error": real.value / e.mid - 1.0,
                    "inside_range": inside, "url": e.url, "actual_url": real.url, "excluded": excluded,
                    "flags": flags})
    return out


def summarize(items: Sequence[Mapping[str, Any]], *, by: str = "source") -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    apart: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for c in items:
        k = (str(c[by]), str(c["metric"]), str(c["horizon"]))
        (apart if c.get("excluded") else groups).setdefault(k, []).append(c)
    out = []
    for (key, metric, horizon) in sorted(groups.keys() | apart.keys()):
        rows = groups.get((key, metric, horizon), [])
        left = apart.get((key, metric, horizon), [])
        if not rows:  # todo apartado: se ve igual, con n = 0 y por qué
            out.append({by: key, "metric": metric, "horizon": horizon, "n": 0, "median_abs_error": None,
                        "median_bias": None, "inside_range": None, "n_ranged": 0, "n_excluded": len(left),
                        "excluded_reasons": sorted({str(c["excluded"]).split(":")[0] for c in left}),
                        "n_extreme": 0})
            continue
        errs = [float(r["error"]) for r in rows]
        ranged = [r for r in rows if r.get("inside_range") is not None]
        out.append({by: key, "metric": metric, "horizon": horizon, "n": len(rows),
                    "n_excluded": len(left),
                    "excluded_reasons": sorted({str(c["excluded"]).split(":")[0] for c in left}),
                    "n_extreme": sum(1 for r in rows if r.get("flags")),
                    "median_abs_error": float(statistics.median(abs(e) for e in errs)),
                    "median_bias": float(statistics.median(errs)),
                    "inside_range": (sum(1 for r in ranged if r["inside_range"]) / len(ranged)) if ranged else None,
                    "n_ranged": len(ranged)})
    return out


def measured_errors(items: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], list[float]]:
    """{(fuente, horizonte): errores} para ``own_consensus.confidence_for`` (firmas → «analista_citado»)."""
    out: dict[tuple[str, str], list[float]] = {}
    for c in items:
        if c.get("excluded"):
            continue
        source = "analista_citado" if str(c["source"]).startswith("analista:") else str(c["source"])
        out.setdefault((source, str(c["horizon"])), []).append(float(c["error"]))
    return out


def guidance_estimates(rows: Sequence[GuidanceRow]) -> list[Estimate]:
    return [Estimate("guia", g.metric, g.period, g.low, g.base, g.high, g.as_of, g.url)
            for g in rows if g.metric in METRICS and g.base]


# ---------------------------------------------------------------------- BD
def _actuals(db: Any, company: Any) -> dict[str, dict[str, Actual]]:
    from app.services.own_consensus import _facts

    return {m: actuals_from_facts(_facts(db, company, FACT_METRIC[m]), metric=m) for m in METRICS}


def _frozen(db: Any, company: Any, tenant_id: int) -> list[Estimate]:
    from sqlalchemy import select

    from app.models.declared_input_value import DeclaredInputValue

    out: list[Estimate] = []
    for row in db.scalars(select(DeclaredInputValue).where(
            DeclaredInputValue.tenant_id == tenant_id, DeclaredInputValue.company_id == company.id,
            DeclaredInputValue.input_key.like("estimate.%")).order_by(DeclaredInputValue.id)).all():
        parts = row.input_key.split(".")
        meta = row.metadata_ or {}
        if len(parts) != 3 or row.base is None or row.as_of is None or not meta.get("source"):
            continue
        out.append(Estimate(str(meta["source"]), parts[1], parts[2], None if row.low is None else float(row.low),
                            float(row.base), None if row.high is None else float(row.high), row.as_of))
    return out


def _analysts(db: Any, company: Any, tenant_id: int) -> list[Estimate]:
    try:
        from app.services.analyst_consensus import CONSENSUS_FIRM, history_for
    except Exception:  # noqa: BLE001
        return []
    out = []
    for e in history_for(db, company, tenant_id):
        if e.metric in METRICS:
            scale = 1.0 if e.metric == "eps" else 1e6
            name = "analista:prensa" if e.firm == CONSENSUS_FIRM else f"analista:{e.firm}"
            out.append(Estimate(name, e.metric, f"fy{e.year}", None, e.value * scale, None, e.as_of, e.url))
    return out


def company_accuracy(db: Any, company: Any, tenant_id: int) -> dict[str, Any]:
    from app.services.own_consensus import _guidance_rows

    acts = _actuals(db, company)
    est = (guidance_estimates(_guidance_rows(db, company, tenant_id, current_only=False))
           + _frozen(db, company, tenant_id) + _analysts(db, company, tenant_id))
    items = cases(est, acts)
    return {"ticker": company.ticker, "version": ACCURACY_VERSION, "cases": items,
            "by_source": summarize(items), "measured_errors": measured_errors(items)}


def freeze_consensus(db: Any, company: Any, tenant_id: int, result: Mapping[str, Any], *,
                     today: date | None = None) -> dict[str, int]:
    """Congela cada celda publicada si cambió (valor, rango o fuente) desde la última foto."""
    from app.services.declared_input_service import DeclaredInput, DeclaredInputService

    today = today or date.today()
    service = DeclaredInputService()
    current = service.current(db, company_id=company.id, tenant_id=tenant_id,
                              keys=[c["key"] for c in result.get("cells", [])])
    stats = {"frozen": 0, "unchanged": 0, "skipped": 0}
    for cell in result.get("cells", []):
        if cell.get("status") != "estimado" or cell.get("mid") is None:
            stats["skipped"] += 1
            continue
        row = current.get((cell["key"], ""))
        meta = {"source": cell["source"], "formula": str(cell.get("formula") or "")[:500],
                "flags": list(cell.get("flags") or []), "version": cell.get("version"),
                "period_end": cell.get("period_end"), "confidence": (cell.get("confidence") or {}).get("level")}
        same = row is not None and (row.metadata_ or {}).get("source") == cell["source"] and all(
            (getattr(row, f) is None and cell[k] is None) or (getattr(row, f) is not None and cell[k] is not None
                                                             and abs(float(getattr(row, f)) - float(cell[k]))
                                                             <= 1e-6 * max(1.0, abs(float(cell[k]))))
            for f, k in (("low", "low"), ("base", "mid"), ("high", "high")))
        if same:
            stats["unchanged"] += 1
            continue
        metric = cell["metric"]
        ccy = (getattr(company, "currency", None) or "USD").strip() or "USD"
        lo, mid, hi = cell["low"], cell["mid"], cell["high"]
        if lo is not None and lo > mid:
            lo = mid
        if hi is not None and hi < mid:
            hi = mid
        item = DeclaredInput(input_key=cell["key"], segment_key="", low=lo, base=mid, high=hi,
                             unit=(f"{ccy}/share" if metric == "eps" else ccy), method="derive", as_of=today,
                             metadata=meta)
        if service.validate(item):
            stats["skipped"] += 1
            continue
        service.upsert(db, company=company, tenant_id=tenant_id, item=item)
        stats["frozen"] += 1
    return stats
