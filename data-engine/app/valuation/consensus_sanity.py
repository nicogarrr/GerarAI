"""Contraste con el consenso: conciliación dato a dato cuando nos alejamos más de un 35 %.

Feature aprobada por Nico (4-nov-2026, equipo de expertos; regla 1 de las
lecciones de la auditoría de ASTS, gerarai-asts3/REPORT.md §8): si
``|nuestro − consenso| / consenso > 35 %`` (o el valor queda fuera del rango
de precios objetivo), el valor no se da por bueno sin una conciliación input a
input: qué input explica la diferencia y cuánto, en $ por acción, con una de
tres etiquetas («aceptamos», «rechazamos (motivo)», «abierta (qué dato la
cierra)»). Si la conciliación no explica la diferencia, el valor queda
marcado «revisar».

Cómo concilia (general, sin nada por ticker):

- ``cascade``: parte de NUESTROS inputs y sustituye uno a uno por los del
  consenso de analistas (en el orden dado), revalorando con el MISMO motor
  (``revalue``) tras cada paso. El efecto de cada paso es el cambio de valor
  por acción. Lo que queda entre el último valor y el consenso es el residuo.
- ``assess``: explicado si el residuo es como mucho ``UNEXPLAINED_SHARE_MAX``
  de la diferencia; si no, «revisar».
- ``consensus_sanity_for_dcf``: adaptador para el DCF FCFF del motor; lee la
  traza del escenario base con ``what_to_believe.dcf_paths_from_trace`` y
  revalora con ``run_path_dcf`` (misma matemática que el valor publicado).
- ``apply_consensus_sanity``: escribe ``trace.consensus_reconciliation`` en el
  resultado de la valoración y, si no se explica, ``review_status='revisar'``
  y el bloqueo ``consenso_sin_conciliar``. Solo con ``EXPERT_TEAM_ENABLED``.

Los inputs del consenso los aporta quien llama (la mezcla de analistas,
las notas de analista de #4582), siempre en las unidades de la traza. Sin
inputs de analistas no hay conciliación posible: si la diferencia supera el
umbral, «revisar». Nada de esto cambia cómo se calcula el valor; el gancho en
thesis_service es de la lane c2acb5b0.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from app.valuation.normalized_fcf import run_path_dcf
from app.valuation.what_to_believe import DcfPaths, dcf_paths_from_trace

#: Diferencia relativa frente al consenso a partir de la cual hace falta conciliar.
CONSENSUS_GAP_THRESHOLD = 0.35
#: Parte de la diferencia que la conciliación puede dejar sin explicar.
UNEXPLAINED_SHARE_MAX = 0.25
STEP_LABELS: tuple[str, ...] = ("aceptamos", "rechazamos", "abierta")
DEFAULT_LABEL = "abierta"
DEFAULT_LABEL_REASON = "sin revisar: falta que el escéptico la acepte o la rechace"
REVIEW_STATUS = "revisar"
REVIEW_BLOCKER = "consenso_sin_conciliar"
#: Orden de la cascada del DCF: primero el negocio (ingresos, crecimiento,
#: margen), luego las tasas y por último el puente EV → acción.
DCF_RECONCILIATION_ORDER: tuple[str, ...] = (
    "revenue",
    "growth",
    "margin",
    "wacc",
    "terminal_growth",
    "net_debt",
    "shares_outstanding",
)
#: Etiqueta legible de cada input del DCF (es) para la ficha.
DCF_INPUT_NAMES: dict[str, str] = {
    "revenue": "ingresos de partida",
    "growth": "crecimiento de los ingresos",
    "margin": "margen de flujo de caja libre",
    "wacc": "WACC",
    "terminal_growth": "crecimiento perpetuo",
    "net_debt": "deuda neta",
    "shares_outstanding": "acciones",
}

Revalue = Callable[[dict[str, Any]], float]


@dataclass(frozen=True)
class StepLabel:
    """Juicio sobre una diferencia: aceptamos, rechazamos (motivo) o abierta (qué dato la cierra)."""

    label: str
    reason: str = ""


@dataclass(frozen=True)
class ReconciliationStep:
    input_key: str
    ours: Any
    theirs: Any
    value_before: float
    value_after: float | None
    label: str = DEFAULT_LABEL
    reason: str = DEFAULT_LABEL_REASON
    source: str | None = None
    error: str | None = None

    @property
    def effect(self) -> float | None:
        return None if self.value_after is None else self.value_after - self.value_before

    def as_dict(self) -> dict[str, Any]:
        return {
            "input": self.input_key,
            "name": DCF_INPUT_NAMES.get(self.input_key, self.input_key),
            "ours": self.ours,
            "theirs": self.theirs,
            "value_before": _round(self.value_before),
            "value_after": _round(self.value_after),
            "effect_per_share": _round(self.effect),
            "label": self.label,
            "reason": self.reason,
            "source": self.source,
            "error": self.error,
        }


@dataclass
class ConsensusSanity:
    """Resultado del contraste con el consenso."""

    # sin_consenso | no_aplica | dentro | explicado | revisar
    status: str
    our_value: float | None = None
    consensus: float | None = None
    gap_pct: float | None = None
    threshold: float = CONSENSUS_GAP_THRESHOLD
    target_low: float | None = None
    target_high: float | None = None
    outside_target_range: bool = False
    consensus_source: str | None = None
    steps: list[ReconciliationStep] = field(default_factory=list)
    explained: float | None = None
    residual: float | None = None
    residual_share: float | None = None
    main_driver: str | None = None
    reason: str | None = None

    @property
    def needs_review(self) -> bool:
        return self.status == REVIEW_STATUS

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "our_value": _round(self.our_value),
            "consensus": _round(self.consensus),
            "gap_pct": _round(self.gap_pct, 4),
            "threshold": self.threshold,
            "target_low": _round(self.target_low),
            "target_high": _round(self.target_high),
            "outside_target_range": self.outside_target_range,
            "consensus_source": self.consensus_source,
            "steps": [s.as_dict() for s in self.steps],
            "explained": _round(self.explained),
            "residual": _round(self.residual),
            "residual_share": _round(self.residual_share, 4),
            "unexplained_share_max": UNEXPLAINED_SHARE_MAX,
            "main_driver": self.main_driver,
            "reason": self.reason,
        }


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


# ---------------------------------------------------------------------------
# Reglas (puras)
# ---------------------------------------------------------------------------


def gap_vs_consensus(our_value: float, consensus: float) -> float:
    """Diferencia relativa con signo: (nuestro − consenso) / consenso."""
    return (our_value - consensus) / consensus


def needs_reconciliation(
    our_value: float,
    consensus: float,
    *,
    target_low: float | None = None,
    target_high: float | None = None,
) -> tuple[bool, bool]:
    """(hace falta conciliar, fuera del rango de objetivos)."""
    outside = (target_low is not None and our_value < target_low) or (
        target_high is not None and our_value > target_high
    )
    return abs(gap_vs_consensus(our_value, consensus)) > CONSENSUS_GAP_THRESHOLD or outside, outside


def cascade(
    ours: Mapping[str, Any],
    theirs: Mapping[str, Any],
    revalue: Revalue,
    *,
    order: Sequence[str],
    labels: Mapping[str, StepLabel] | None = None,
    sources: Mapping[str, str] | None = None,
) -> tuple[float, list[ReconciliationStep]]:
    """Sustituye nuestros inputs por los del consenso uno a uno y revalora tras cada paso.

    Devuelve (nuestro valor recalculado, pasos). Un paso que el motor no puede
    calcular queda con ``error`` y no se aplica (su efecto va al residuo).
    Solo entran los inputs que el consenso da y que difieren de los nuestros.
    """
    labels = labels or {}
    sources = sources or {}
    current = dict(ours)
    start = revalue(dict(current))
    value = start
    steps: list[ReconciliationStep] = []
    for key in order:
        if key not in theirs or theirs[key] is None or key not in current:
            continue
        if theirs[key] == current[key]:
            continue
        trial = dict(current)
        trial[key] = theirs[key]
        label = labels.get(key) or StepLabel(DEFAULT_LABEL, DEFAULT_LABEL_REASON)
        try:
            after = _finite(revalue(dict(trial)))
            error = None if after is not None else "el motor no da un valor finito"
        except Exception as exc:  # p. ej. WACC ≤ g: el paso no es calculable
            after, error = None, f"{type(exc).__name__}"
        steps.append(
            ReconciliationStep(
                input_key=key,
                ours=current[key],
                theirs=theirs[key],
                value_before=value,
                value_after=after,
                label=label.label if label.label in STEP_LABELS else DEFAULT_LABEL,
                reason=label.reason,
                source=sources.get(key),
                error=error,
            )
        )
        if after is not None:
            current = trial
            value = after
    return start, steps


def assess(
    our_value: float | None,
    consensus: float | None,
    *,
    steps: Sequence[ReconciliationStep] = (),
    start_value: float | None = None,
    target_low: float | None = None,
    target_high: float | None = None,
    consensus_source: str | None = None,
) -> ConsensusSanity:
    """Decide si hace falta conciliar y, si hace falta, si los pasos explican la diferencia."""
    if consensus is None or not isfinite(consensus) or consensus <= 0:
        return ConsensusSanity(status="sin_consenso", our_value=our_value, reason="sin consenso de analistas")
    if our_value is None or not isfinite(our_value):
        return ConsensusSanity(status="no_aplica", consensus=consensus, reason="sin valor propio publicado")
    needed, outside = needs_reconciliation(
        our_value, consensus, target_low=target_low, target_high=target_high
    )
    out = ConsensusSanity(
        status="dentro",
        our_value=our_value,
        consensus=consensus,
        gap_pct=gap_vs_consensus(our_value, consensus),
        target_low=target_low,
        target_high=target_high,
        outside_target_range=outside,
        consensus_source=consensus_source,
    )
    if not needed:
        return out
    out.steps = list(steps)
    base = start_value if start_value is not None else our_value
    applied = [s for s in steps if s.value_after is not None]
    last = applied[-1].value_after if applied else base
    assert last is not None
    gap = consensus - our_value
    out.explained = last - base
    out.residual = consensus - last
    out.residual_share = abs(out.residual) / abs(gap) if gap else 0.0
    if applied:
        biggest = max(applied, key=lambda s: abs(s.effect or 0.0))
        out.main_driver = biggest.input_key
    if not steps:
        out.status = REVIEW_STATUS
        out.reason = "sin inputs del consenso con los que conciliar la diferencia"
    elif out.residual_share <= UNEXPLAINED_SHARE_MAX:
        out.status = "explicado"
        out.reason = (
            f"la diferencia la explica sobre todo {DCF_INPUT_NAMES.get(out.main_driver or '', out.main_driver)}"
            if out.main_driver
            else "explicado"
        )
    else:
        out.status = REVIEW_STATUS
        out.reason = (
            f"la conciliación deja sin explicar el {out.residual_share:.0%} de la diferencia "
            f"(máximo {UNEXPLAINED_SHARE_MAX:.0%})"
        )
    return out


# ---------------------------------------------------------------------------
# Adaptador para el DCF FCFF del motor
# ---------------------------------------------------------------------------


def _dcf_inputs(paths: DcfPaths) -> dict[str, Any]:
    return {
        "revenue": paths.revenue,
        "growth": list(paths.growth_path),
        "margin": list(paths.margin_path),
        "wacc": paths.wacc,
        "terminal_growth": paths.terminal_growth,
        "net_debt": paths.net_debt,
        "shares_outstanding": paths.shares_outstanding,
    }


def _path(raw: Any, years: int) -> list[float] | None:
    """Un escalar se aplica a todos los años; una lista debe tener los años del DCF."""
    scalar = _finite(raw)
    if scalar is not None:
        return [scalar] * years
    if isinstance(raw, list | tuple) and len(raw) == years:
        values = [_finite(v) for v in raw]
        if all(v is not None for v in values):
            return [float(v) for v in values if v is not None]
    return None


def _normalize_theirs(theirs: Mapping[str, Any], years: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, raw in theirs.items():
        if key in {"growth", "margin"}:
            path = _path(raw, years)
            if path is not None:
                out[key] = path
        elif key in DCF_RECONCILIATION_ORDER:
            value = _finite(raw)
            if value is not None:
                out[key] = value
    return out


def dcf_revalue(paths: DcfPaths) -> Revalue:
    """Revalora el DCF base con otros inputs (misma matemática que el valor publicado)."""

    def revalue(inputs: dict[str, Any]) -> float:
        return run_path_dcf(
            revenue=float(inputs["revenue"]),
            growth_path=list(inputs["growth"]),
            margin_path=list(inputs["margin"]),
            wacc=float(inputs["wacc"]),
            terminal_growth=float(inputs["terminal_growth"]),
            net_debt=float(inputs["net_debt"]),
            shares_outstanding=float(inputs["shares_outstanding"]),
            minority_interest=paths.minority_interest,
            preferred_stock=paths.preferred_stock,
        ).value_per_share

    return revalue


def _base_trace(valuation: Mapping[str, Any]) -> Any:
    trace = valuation.get("trace")
    if not isinstance(trace, dict):
        return None
    scenarios = trace.get("scenarios")
    if isinstance(scenarios, dict) and isinstance(scenarios.get("base"), dict):
        return scenarios["base"].get("trace")
    return trace if trace.get("method") else None


def consensus_sanity_for_dcf(
    valuation: Mapping[str, Any],
    *,
    consensus: float | None,
    analyst_inputs: Mapping[str, Any] | None = None,
    our_value: float | None = None,
    labels: Mapping[str, StepLabel] | None = None,
    sources: Mapping[str, str] | None = None,
    target_low: float | None = None,
    target_high: float | None = None,
    consensus_source: str | None = None,
) -> ConsensusSanity:
    """Contraste con el consenso de un resultado de ``ValuationService.value_company``.

    ``analyst_inputs`` usa las claves de ``DCF_RECONCILIATION_ORDER`` en las
    unidades de la traza (tasas en decimal; crecimiento y margen como escalar
    o como lista de los años del DCF). ``our_value`` por defecto es el DCF
    base reconstruido de la traza.
    """
    paths = dcf_paths_from_trace(_base_trace(valuation))
    if paths is None:
        sanity = assess(
            our_value,
            consensus,
            target_low=target_low,
            target_high=target_high,
            consensus_source=consensus_source,
        )
        if sanity.status == REVIEW_STATUS:
            sanity.reason = "el motor no es un DCF reconstruible: conciliación manual pendiente"
        return sanity
    revalue = dcf_revalue(paths)
    theirs = _normalize_theirs(analyst_inputs or {}, len(paths.growth_path))
    start, steps = cascade(
        _dcf_inputs(paths), theirs, revalue, order=DCF_RECONCILIATION_ORDER, labels=labels, sources=sources
    )
    return assess(
        our_value if our_value is not None else start,
        consensus,
        steps=steps,
        start_value=start,
        target_low=target_low,
        target_high=target_high,
        consensus_source=consensus_source,
    )


def apply_consensus_sanity(
    result: dict[str, Any], sanity: ConsensusSanity, *, enabled: bool | None = None
) -> dict[str, Any]:
    """Escribe ``trace.consensus_reconciliation``; sin explicar → «revisar» y bloqueo de publicación.

    ``enabled`` None = ``EXPERT_TEAM_ENABLED``; apagado devuelve el resultado intacto.
    """
    if enabled is None:
        from app.core.config import get_settings

        enabled = bool(get_settings().expert_team_enabled)
    if not enabled:
        return result
    trace = result.get("trace")
    if not isinstance(trace, dict):
        trace = {}
        result["trace"] = trace
    trace["consensus_reconciliation"] = sanity.as_dict()
    if sanity.needs_review:
        result["review_status"] = REVIEW_STATUS
        blockers = list(result.get("publication_blockers") or [])
        if REVIEW_BLOCKER not in blockers:
            blockers.append(REVIEW_BLOCKER)
        result["publication_blockers"] = blockers
        result["publishable"] = False
    return result


__all__ = [
    "CONSENSUS_GAP_THRESHOLD",
    "DCF_RECONCILIATION_ORDER",
    "REVIEW_BLOCKER",
    "REVIEW_STATUS",
    "STEP_LABELS",
    "UNEXPLAINED_SHARE_MAX",
    "ConsensusSanity",
    "ReconciliationStep",
    "StepLabel",
    "apply_consensus_sanity",
    "assess",
    "cascade",
    "consensus_sanity_for_dcf",
    "dcf_revalue",
    "gap_vs_consensus",
    "needs_reconciliation",
]
