"""Motor de escenarios ponderados por probabilidad para empresas con ingresos.

Para la familia de métodos declarados de escenarios, capacidad o cartera de
pedidos («scenario_auto_energy_fsd», «defense_backlog_scenario_model»,
«capacity_capex_utilization_model»; ver ``registry.declared_method_engines``),
que hasta el 4-nov-2026 no tenían motor y corrían el DCF estándar.

Cómo valora:

1. Corre el DCF estándar completo (mismo snapshot, ventas, WACC, g terminal,
   plan de proyección y puente EV -> equity). Este motor NO cambia ninguna de
   esas reglas: las reutiliza (``StandardDCFEngine.resolved_inputs``).
2. Toma los escenarios declarados EN DATOS, con su fuente
   (``app/data/valuation_scenarios.py``). Sin juego con fuente no hay valor
   por escenarios (abajo).
3. Valora cada escenario con su método:
   - ``dcf``: el mismo DCF (plano o con plan) con el crecimiento y/o el margen
     del escenario;
   - ``forward_multiple``: FCF de los años 1..N más múltiplo x métrica del año
     N (ventas o FCF), descontados al WACC del DCF base.
4. Valor razonable = suma ponderada por probabilidad (valores brutos: un
   escenario negativo cuenta, como en el DCF estándar). Cada escenario, su
   peso, su método y sus supuestos van a la traza (``trace.scenario_set``).

Sin juego por defecto (Nico, 4-nov-2026: «Que tengan escenarios reales, no
hardcodeo»): ningún juego genérico de bajista/base/alcista se fabrica a partir
de las entradas de la empresa. Los escenarios con fuente llegarán como datos
declarados (etapa de expertos de la tesis). El WACC y la g terminal no se tocan
en ningún escenario: los escenarios describen el negocio, no la tasa.

Respaldo (al motor que resolvería la clasificación sin esta ruta, con el
motivo en ``trace.engine_fallback``): sin escenarios con fuente
(``scenario_set_missing``, detalle «escenarios pendientes: sin escenarios con
fuente»), sin ingresos positivos
(``scenario_requires_revenue``), sin DCF base válido, p. ej. una empresa que
quema caja, también cuando solo el margen normalizado de ciclo medio la haría
rentable (``scenario_base_dcf_unavailable``), o escenarios declarados
inválidos (``scenario_inputs_invalid``, con el detalle).
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Any

from app.data.valuation_scenarios import VALUATION_SCENARIOS
from app.valuation.dcf_fcff import WaccNotAboveTerminalGrowthError
from app.valuation.engines.base import (
    ValuationContext,
    ValuationEngine,
    apply_publication_blockers,
    margin_of_safety,
    scenario_definition_trace,
)
from app.valuation.engines.standard_dcf import StandardDCFEngine, _run_scenario
from app.valuation.normalized_fcf import plausibility_warning
from app.valuation.scenario_definitions import ScenarioDefinition
from app.valuation.scenario_model import Scenario, probability_weighted_value

SCENARIO_ENGINE_KEY = "scenario"

# Motivos de respaldo que escribe este motor en ``trace.engine_fallback``.
SCENARIO_FALLBACK_REASONS = frozenset(
    {
        "scenario_set_missing",
        "scenario_requires_revenue",
        "scenario_base_dcf_unavailable",
        "scenario_inputs_invalid",
    }
)
# Sin juego de escenarios con fuente: no se publica valor por escenarios.
SCENARIO_SET_MISSING_DETAIL = "escenarios pendientes: sin escenarios con fuente"

PROBABILITY_TOLERANCE = 0.01
METHODS = frozenset({"dcf", "forward_multiple"})
FORWARD_METRICS = frozenset({"revenue", "fcf"})
MAX_FORWARD_YEAR = 10
# Mismos topes que el DCF estándar.
GROWTH_FLOOR, GROWTH_CEILING = -0.15, 0.45
MARGIN_CEILING = 0.50
# Campos que un escenario puede llevar; el WACC y la g terminal no están.
ALLOWED_FIELDS = frozenset(
    {"name", "probability", "method", "revenue_growth", "fcf_margin", "metric", "multiple",
     "year", "description"}
)

class ScenarioInputsError(ValueError):
    """Escenarios declarados inválidos (el mensaje es el detalle)."""


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    probability: float
    method: str
    revenue_growth: float
    fcf_margin: float
    metric: str | None = None
    multiple: float | None = None
    year: int | None = None
    description: str = ""


@dataclass(frozen=True)
class ForwardMultipleResult:
    value_per_share: float
    trace: dict


def _finite(value: Any, field: str, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ScenarioInputsError(f"escenario «{name}»: {field} no es un número finito")
    return float(value)


def parse_scenarios(raw: Any, *, base_growth: float, base_margin: float) -> list[ScenarioSpec]:
    """Valida los escenarios declarados; sin crecimiento/margen, los del base."""
    if not isinstance(raw, list) or not raw:
        raise ScenarioInputsError("la lista de escenarios está vacía o no es una lista")
    specs: list[ScenarioSpec] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ScenarioInputsError("cada escenario debe ser un objeto")
        name = str(item.get("name") or "").strip()
        if not name:
            raise ScenarioInputsError("un escenario no tiene nombre")
        if name in seen:
            raise ScenarioInputsError(f"escenario «{name}» repetido")
        seen.add(name)
        extra = sorted(set(item) - ALLOWED_FIELDS)
        if extra:
            raise ScenarioInputsError(
                f"escenario «{name}»: campos no admitidos {extra} (el WACC y la g terminal "
                "los fija el DCF base)"
            )
        probability = _finite(item.get("probability"), "probability", name)
        if not 0.0 < probability <= 1.0:
            raise ScenarioInputsError(f"escenario «{name}»: probabilidad {probability} fuera de (0, 1]")
        method = str(item.get("method") or "").strip()
        if method not in METHODS:
            raise ScenarioInputsError(f"escenario «{name}»: método «{method}» desconocido")
        growth = _finite(item.get("revenue_growth", base_growth), "revenue_growth", name)
        margin = _finite(item.get("fcf_margin", base_margin), "fcf_margin", name)
        if not GROWTH_FLOOR <= growth <= GROWTH_CEILING:
            raise ScenarioInputsError(
                f"escenario «{name}»: crecimiento {growth} fuera de [{GROWTH_FLOOR}, {GROWTH_CEILING}]"
            )
        if margin > MARGIN_CEILING:
            raise ScenarioInputsError(f"escenario «{name}»: margen {margin} por encima de {MARGIN_CEILING}")
        metric = multiple = year = None
        if method == "forward_multiple":
            metric = str(item.get("metric") or "").strip()
            if metric not in FORWARD_METRICS:
                raise ScenarioInputsError(f"escenario «{name}»: métrica «{metric}» no admitida")
            multiple = _finite(item.get("multiple"), "multiple", name)
            if multiple <= 0:
                raise ScenarioInputsError(f"escenario «{name}»: el múltiplo debe ser positivo")
            year_raw = item.get("year")
            if isinstance(year_raw, bool) or not isinstance(year_raw, int) or not 1 <= year_raw <= MAX_FORWARD_YEAR:
                raise ScenarioInputsError(f"escenario «{name}»: año {year_raw!r} fuera de 1..{MAX_FORWARD_YEAR}")
            year = year_raw
        specs.append(
            ScenarioSpec(
                name=name,
                probability=probability,
                method=method,
                revenue_growth=growth,
                fcf_margin=margin,
                metric=metric,
                multiple=multiple,
                year=year,
                description=str(item.get("description") or ""),
            )
        )
    total = sum(spec.probability for spec in specs)
    if abs(total - 1.0) > PROBABILITY_TOLERANCE:
        raise ScenarioInputsError(f"las probabilidades suman {total:.4f}, no 1 (±{PROBABILITY_TOLERANCE})")
    return specs


def forward_multiple_value(spec: ScenarioSpec, inputs: dict) -> ForwardMultipleResult:
    """FCF de los años 1..N + múltiplo x métrica del año N, al WACC del base."""
    assert spec.year is not None and spec.multiple is not None and spec.metric is not None
    wacc = float(inputs["wacc"])
    revenue = float(inputs["revenue"])
    pv_fcf = 0.0
    for year in range(1, spec.year + 1):
        revenue *= 1 + spec.revenue_growth
        pv_fcf += revenue * spec.fcf_margin / (1 + wacc) ** year
    metric_value = revenue if spec.metric == "revenue" else revenue * spec.fcf_margin
    exit_value = spec.multiple * metric_value
    pv_exit = exit_value / (1 + wacc) ** spec.year
    enterprise_value = pv_fcf + pv_exit
    equity_value = (
        enterprise_value
        - float(inputs["net_debt"])
        - float(inputs["minority_interest"])
        - float(inputs["preferred_stock"])
    )
    value_per_share = equity_value / float(inputs["shares"])
    return ForwardMultipleResult(
        value_per_share=value_per_share,
        trace={
            "method": "forward_multiple",
            "metric": spec.metric,
            "multiple": spec.multiple,
            "year": spec.year,
            "metric_value_at_year": metric_value,
            "pv_explicit_fcf": pv_fcf,
            "pv_exit_value": pv_exit,
            "enterprise_value": enterprise_value,
            "equity_value": equity_value,
            "wacc": wacc,
        },
    )


def declared_scenario_entry(company: Any) -> dict | None:
    ticker = (getattr(company, "ticker", None) or "").strip().upper()
    entry = VALUATION_SCENARIOS.get(ticker)
    return entry if isinstance(entry, dict) else None


class ScenarioValuationEngine(ValuationEngine):
    key = SCENARIO_ENGINE_KEY

    def value(self, context: ValuationContext) -> dict:
        company = context.company
        revenue = context.snapshot.value("revenue")
        dcf_engine = StandardDCFEngine()
        dcf_context = dataclasses.replace(context, engine_key=dcf_engine.key)
        entry = declared_scenario_entry(company)
        if entry is None:
            return self._fallback(context, None, "scenario_set_missing", SCENARIO_SET_MISSING_DETAIL)
        if revenue is None or revenue <= 0:
            return self._fallback(
                context, None, "scenario_requires_revenue",
                "sin ingresos positivos en el snapshot no hay escenarios de negocio",
            )
        base = dcf_engine.value(dcf_context)
        inputs = dcf_engine.resolved_inputs
        # «partial» = DCF calculado con bloqueos de publicación (p. ej. WACC
        # sin fuente fechada): los escenarios heredan esos bloqueos.
        if base.get("status") not in ("ok", "partial") or inputs is None:
            return self._fallback(
                context, base, "scenario_base_dcf_unavailable",
                str((base.get("trace") or {}).get("reason") or base.get("status") or "sin DCF base"),
            )
        plan = inputs["plan"]
        start_margin = getattr(plan, "margin_start", None)
        if start_margin is not None and start_margin <= 0:
            # Quema caja hoy y solo el margen normalizado de ciclo medio la
            # hace rentable: eso es terreno del motor de clasificación
            # (pre_revenue / funding gap), que no sustituye un margen reportado
            # negativo por uno inferido. Los escenarios no inventan esa cifra.
            return self._fallback(
                context, base, "scenario_base_dcf_unavailable",
                f"margen FCF reportado {start_margin:.4f} (quema caja); solo el margen "
                "normalizado de ciclo medio lo haría positivo",
            )
        base_growth = float(inputs["revenue_growth"])
        base_margin = float(inputs["fcf_margin"])
        try:
            if not str(entry.get("source") or "").strip():
                raise ScenarioInputsError("el juego de escenarios no declara su fuente")
            specs = parse_scenarios(entry.get("scenarios"), base_growth=base_growth, base_margin=base_margin)
        except ScenarioInputsError as exc:
            return self._fallback(context, base, "scenario_inputs_invalid", str(exc))
        try:
            return self._weighted_result(base, inputs, specs, entry=entry)
        except (WaccNotAboveTerminalGrowthError, ValueError, ZeroDivisionError) as exc:
            return self._fallback(context, base, "scenario_inputs_invalid", f"{type(exc).__name__}: {exc}")

    def _weighted_result(self, base: dict, inputs: dict, specs: list[ScenarioSpec], *, entry: dict) -> dict:
        result = dict(base)
        trace = dict(base.get("trace") or {})
        scenario_results: dict[str, dict] = {}
        summary: list[dict] = []
        for spec in specs:
            assumptions: dict[str, Any] = {
                "revenue_growth": spec.revenue_growth,
                "fcf_margin": spec.fcf_margin,
                "wacc": float(inputs["wacc"]),
                "terminal_growth": float(inputs["terminal_growth"]),
            }
            if spec.method == "dcf":
                run = _run_scenario(
                    inputs["plan"],
                    revenue=float(inputs["revenue"]),
                    assumptions=assumptions,
                    base_margin=float(inputs["fcf_margin"]),
                    net_debt=float(inputs["net_debt"]),
                    shares=float(inputs["shares"]),
                    minority_interest=float(inputs["minority_interest"]),
                    preferred_stock=float(inputs["preferred_stock"]),
                )
                value, run_trace = float(run.value_per_share), run.trace
            else:
                fm = forward_multiple_value(spec, inputs)
                value, run_trace = fm.value_per_share, fm.trace
                assumptions.update({"metric": spec.metric, "multiple": spec.multiple, "year": spec.year})
            definition = ScenarioDefinition(
                name=spec.name,
                probability=spec.probability,
                assumptions=assumptions,
                drivers=[spec.method],
                description=spec.description,
            )
            scenario_results[spec.name] = {
                "definition": scenario_definition_trace(definition),
                "value_per_share": value,
                "trace": run_trace,
            }
            summary.append(
                {
                    "name": spec.name,
                    "probability": spec.probability,
                    "method": spec.method,
                    "value_per_share": value,
                    "assumptions": assumptions,
                    "description": spec.description,
                }
            )

        weighted = probability_weighted_value(
            [Scenario(item["name"], item["probability"], item["value_per_share"]) for item in summary]
        )
        expected_raw = float(weighted["expected_value"])
        # Convención d2656966: un valor <= 0 no se publica como cifra.
        scenario_notes: dict[str, str] = {}
        for item in summary:
            if item["value_per_share"] <= 0:
                note = (
                    f"Escenario «{item['name']}»: valor por acción {item['value_per_share']:.2f} "
                    "con estos supuestos: N/D, no se publica una cifra negativa."
                )
                scenario_notes[item["name"]] = note
                item["value_note"] = note
        expected = expected_raw if expected_raw > 0 else None

        def shown(value: float) -> float | None:
            return value if value > 0 else None

        by_value = sorted(summary, key=lambda item: item["value_per_share"])
        base_item = next((item for item in summary if item["name"] == "base"), None) or max(
            summary, key=lambda item: item["probability"]
        )
        bear = shown(by_value[0]["value_per_share"])
        bull = shown(by_value[-1]["value_per_share"])
        base_value = shown(base_item["value_per_share"])

        comparable_price = trace.get("comparable_price")
        ratio = result.get("adr_ratio")
        result.update(
            {
                "bear_value": bear,
                "base_value": base_value,
                "bull_value": bull,
                "expected_value": expected,
                "margin_of_safety": margin_of_safety(expected, comparable_price),
                "scenario_notes": scenario_notes,
                "listed_share_values": (
                    {
                        "bear": bear * ratio if bear is not None else None,
                        "base": base_value * ratio if base_value is not None else None,
                        "bull": bull * ratio if bull is not None else None,
                        "expected": expected * ratio if expected is not None else None,
                    }
                    if ratio
                    else None
                ),
            }
        )
        warning = plausibility_warning(expected, comparable_price)
        result.pop("plausibility_warning", None)
        trace.pop("plausibility_warning", None)
        if warning is not None:
            result["plausibility_warning"] = warning
            trace["plausibility_warning"] = warning
        trace.update(
            {
                "engine": self.key,
                "scenario_style": "declared_scenarios",
                "probability_method": "declared_in_data",
                "scenarios": scenario_results,
                "weighted": weighted["trace"],
                "expected_value_raw": expected_raw,
                "scenario_notes": scenario_notes,
                "scenario_set": {
                    "source": "declared",
                    "data_source": entry.get("source"),
                    "probability_sum": weighted["trace"]["probability_sum"],
                    "base_dcf": {
                        "expected_value": base.get("expected_value"),
                        "base_value": base.get("base_value"),
                    },
                    "scenarios": summary,
                },
            }
        )
        result["trace"] = trace
        return apply_publication_blockers(result)

    def _fallback(self, context: ValuationContext, base: dict | None, reason: str, detail: str) -> dict:
        from app.valuation.engines.registry import VALUATION_ENGINES, classification_engine_key

        company = context.company
        engine_key = classification_engine_key(company)
        if engine_key == StandardDCFEngine.key and base is not None:
            result = base
        else:
            engine_cls = VALUATION_ENGINES.get(engine_key, StandardDCFEngine)
            engine = engine_cls()
            result = engine.value(dataclasses.replace(context, engine_key=engine.key))
            engine_key = engine.key
        declared = (getattr(company, "valuation_model", None) or "").strip()
        trace = result.setdefault("trace", {})
        trace["engine_fallback"] = {
            "declared_model": declared,
            "declared_method": declared.lower().split("+", 1)[0].strip(),
            "resolved_engine": engine_key,
            "reason": reason,
            "detail": detail[:500],
        }
        return result
