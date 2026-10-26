"""Deterministic, company-specific operating formulas.

The registry deliberately contains formulas rather than prose-only driver lists.
Every projected value starts from a sourced company fact. Scenario policies may
change a sourced historical trend, but a missing starting observation is never
replaced with a plausible number.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from typing import Any

from app.models import FinancialFact
from app.services.company_framework import CompanyFramework
from app.services.driver_dimensions import DriverDimensionValidator

RATE_DRIVERS = {
    "penetration",
    "revenue_share",
    "utilization",
    "take_rate",
    "churn",
    "retention",
    "backlog_conversion",
    "fee_rate",
    "cash_yield",
    "occupancy",
    "royalty_rate",
    "premium_growth",
    "return_on_tangible_equity",
    "roe",
    "combined_ratio",
    "organic_growth",
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


@dataclass(frozen=True)
class FormulaDefinition:
    key: str
    inputs: tuple[str, ...]
    output_metric: str
    evaluate: Callable[[dict[str, float]], tuple[float, dict[str, float]]]
    expression: str


def _single(segment: str, expression: Callable[[dict[str, float]], float]):
    def evaluate(values: dict[str, float]) -> tuple[float, dict[str, float]]:
        output = expression(values)
        return output, {segment: output}

    return evaluate


def _space_network(values: dict[str, float]) -> tuple[float, dict[str, float]]:
    demand = (
        values["addressable_subscribers"]
        * values["penetration"]
        * values["monthly_arpu"]
        * 12
        * values["revenue_share"]
    )
    capacity = (
        values["satellites"]
        * values["capacity_per_satellite"]
        * values["utilization"]
        * values["price_per_gb"]
    )
    # Capacity is a physical ceiling, not an additive revenue segment.
    return min(demand, capacity), {
        "connectivity_demand": demand,
        "connectivity_capacity_ceiling": capacity,
        "connectivity": min(demand, capacity),
    }


def _space_defense(values: dict[str, float]) -> tuple[float, dict[str, float]]:
    launch = values["launches"] * values["price_per_launch"]
    systems = values["backlog"] * values["backlog_conversion"]
    return launch + systems, {"launch": launch, "space_systems": systems}


FORMULAS: dict[str, FormulaDefinition] = {
    "space_network": FormulaDefinition(
        "space_network_capacity_constrained_demand",
        (
            "addressable_subscribers",
            "penetration",
            "monthly_arpu",
            "revenue_share",
            "satellites",
            "capacity_per_satellite",
            "utilization",
            "price_per_gb",
        ),
        "revenue",
        _space_network,
        "min(subscribers*penetration*monthly_arpu*12*revenue_share, satellites*capacity_per_satellite*utilization*price_per_gb)",
    ),
    "space_defense": FormulaDefinition(
        "launch_plus_backlog_conversion",
        ("launches", "price_per_launch", "backlog", "backlog_conversion"),
        "revenue",
        _space_defense,
        "launches*price_per_launch + backlog*backlog_conversion",
    ),
    "platform": FormulaDefinition(
        "payment_volume_monetization",
        ("tpv", "take_rate"),
        "revenue",
        _single("core_platform", lambda v: v["tpv"] * v["take_rate"]),
        "tpv*take_rate",
    ),
    "subscriber": FormulaDefinition(
        "subscriber_monetization",
        ("subscribers", "monthly_arpu"),
        "revenue",
        _single("subscription", lambda v: v["subscribers"] * v["monthly_arpu"] * 12),
        "subscribers*monthly_arpu*12",
    ),
    "software_ai": FormulaDefinition(
        "recurring_revenue_run_rate",
        ("arr",),
        "revenue",
        _single("subscription_and_consumption", lambda v: v["arr"]),
        "arr",
    ),
    "capacity_infrastructure": FormulaDefinition(
        "capacity_utilization_pricing",
        ("capacity_units", "utilization", "price_per_unit"),
        "revenue",
        _single(
            "capacity",
            lambda v: v["capacity_units"] * v["utilization"] * v["price_per_unit"],
        ),
        "capacity_units*utilization*price_per_unit",
    ),
    "holding_asset_manager": FormulaDefinition(
        "fee_related_revenue",
        ("aum", "fee_rate"),
        "revenue",
        _single("asset_management", lambda v: v["aum"] * v["fee_rate"]),
        "aum*fee_rate",
    ),
    "bank": FormulaDefinition(
        "tangible_equity_earnings",
        ("tangible_book_value", "return_on_tangible_equity"),
        "net_income",
        _single(
            "banking_earnings",
            lambda v: v["tangible_book_value"] * v["return_on_tangible_equity"],
        ),
        "tangible_book_value*return_on_tangible_equity",
    ),
    "insurer": FormulaDefinition(
        "earned_premium_run_rate",
        ("earned_premiums",),
        "revenue",
        _single("underwriting", lambda v: v["earned_premiums"]),
        "earned_premiums",
    ),
    "reit": FormulaDefinition(
        "property_net_operating_income",
        ("net_operating_income",),
        "operating_income",
        _single("property_portfolio", lambda v: v["net_operating_income"]),
        "net_operating_income",
    ),
    "commodity": FormulaDefinition(
        "production_realized_price",
        ("production_volume", "realized_price"),
        "revenue",
        _single("resource", lambda v: v["production_volume"] * v["realized_price"]),
        "production_volume*realized_price",
    ),
    "biotech_pre_fcf": FormulaDefinition(
        "reported_revenue_bridge",
        ("revenue",),
        "revenue",
        _single("reported_business", lambda v: v["revenue"]),
        "reported_revenue projected from its sourced historical series; no pipeline value is assumed",
    ),
    "advertising_platform": FormulaDefinition(
        "reported_ad_revenue_bridge",
        ("revenue",),
        "revenue",
        _single("family_of_apps", lambda v: v["revenue"]),
        # Meta desglosa las VARIACIONES interanuales de impresiones y precio
        # por anuncio, no los absolutos: la identidad impresiones × precio no
        # es calculable con hechos publicados y exigirla seria inventar una
        # demanda imposible. El ancla es el ingreso reportado; el detalle de
        # drivers vive en los KPIs del marco (extraccion desde resultados).
        "reported_revenue projected from its sourced historical series; ad impression and price-per-ad absolutes are not disclosed",
    ),
    "generic_fcf": FormulaDefinition(
        "reported_revenue_bridge",
        ("revenue",),
        "revenue",
        _single("reported_business", lambda v: v["revenue"]),
        "reported_revenue projected from its sourced historical series",
    ),
}


class DriverOperatingModel:
    """Project sourced drivers and execute the selected framework formula."""

    def build(
        self,
        framework: CompanyFramework,
        fact_cache: dict[str, list[FinancialFact]],
        *,
        latest_year: int,
        horizon: int,
        scenario: str,
        assumption_overrides: dict[
            str, dict[int, dict[str, dict[str, Any]]]
        ] | None = None,
    ) -> dict[str, Any]:
        definition = FORMULAS[framework.key]
        missing = [key for key in definition.inputs if not self._annual_points(fact_cache.get(key, []))]
        if missing:
            return {
                "status": "missing_formula_inputs",
                "formula_key": definition.key,
                "output_metric": definition.output_metric,
                "expression": definition.expression,
                "missing_inputs": missing,
                "driver_forecasts": {},
                "years": [],
            }

        dimensional_validation = DriverDimensionValidator().validate(
            framework.key, fact_cache
        )
        if not dimensional_validation["valid"]:
            return {
                "status": "invalid_driver_dimensions",
                "formula_key": definition.key,
                "output_metric": definition.output_metric,
                "expression": definition.expression,
                "missing_inputs": [],
                "dimension_errors": dimensional_validation["errors"],
                "dimensional_validation": dimensional_validation,
                "driver_forecasts": {},
                "years": [],
            }

        projected: dict[str, list[dict[str, Any]]] = {}
        for key in definition.inputs:
            projected[key] = self._project_driver(
                key,
                fact_cache[key],
                latest_year=latest_year,
                horizon=horizon,
                scenario=scenario,
                assumption_overrides=assumption_overrides or {},
            )

        rows: list[dict[str, Any]] = []
        for offset in range(horizon):
            values = {key: projected[key][offset]["value"] for key in definition.inputs}
            output, segments = definition.evaluate(values)
            source_ids = sorted(
                {
                    fact_id
                    for key in definition.inputs
                    for fact_id in projected[key][offset]["source_fact_ids"]
                }
            )
            rows.append(
                {
                    "year": latest_year + offset + 1,
                    "output": output,
                    "output_metric": definition.output_metric,
                    "segments": segments,
                    "drivers": values,
                    "source_fact_ids": source_ids,
                    "calculation": definition.expression,
                    "output_dimension": dimensional_validation["output_dimension"],
                }
            )
        return {
            "status": "driver_based",
            "formula_key": definition.key,
            "output_metric": definition.output_metric,
            "expression": definition.expression,
            "missing_inputs": [],
            "dimensional_validation": dimensional_validation,
            "driver_forecasts": projected,
            "years": rows,
        }

    def _project_driver(
        self,
        key: str,
        facts: list[FinancialFact],
        *,
        latest_year: int,
        horizon: int,
        scenario: str,
        assumption_overrides: dict[str, dict[int, dict[str, dict[str, Any]]]],
    ) -> list[dict[str, Any]]:
        points = self._annual_points(facts)
        latest = points[-1]
        trend = self._cagr(points)
        trend_source = "historical_driver_cagr" if trend is not None else "hold_latest_sourced_value"
        base_change = trend or 0.0
        scenario_shift = {"bear": -0.02, "base": 0.0, "bull": 0.02}[scenario]
        change = max(-0.50, min(0.50, base_change + scenario_shift))
        value = latest[1]
        result: list[dict[str, Any]] = []
        for offset in range(1, horizon + 1):
            year = latest_year + offset
            override = (
                assumption_overrides.get(key, {}).get(year, {}).get(scenario)
            )
            if override is not None:
                value = float(override["value"])
            elif key in RATE_DRIVERS:
                value = value * (1 + change)
                if key in {"penetration", "revenue_share", "utilization", "take_rate", "churn", "retention", "backlog_conversion", "fee_rate", "cash_yield", "occupancy", "royalty_rate", "return_on_tangible_equity", "roe"}:
                    value = max(0.0, min(1.0, value))
            else:
                value = value * (1 + change)
            result.append(
                {
                    "year": year,
                    "value": value,
                    "unit": latest[3],
                    "source_fact_ids": [point[2] for point in points],
                    "assumption": (
                        {
                            **override,
                            "source": override["source"],
                            "method": "versioned_driver_override",
                        }
                        if override is not None
                        else {
                            "change": change,
                            "source": trend_source,
                            "historical_change": trend,
                            "scenario_shift": scenario_shift,
                            "user_override": False,
                        }
                    ),
                }
            )
        return result

    @staticmethod
    def _annual_points(facts: list[FinancialFact]) -> list[tuple[int, float, int, str]]:
        by_year: dict[int, tuple[int, float, int, str]] = {}
        for fact in facts:
            value = _number(fact.value)
            if fact.fiscal_year is None or value is None:
                continue
            quarter = (fact.fiscal_quarter or "").upper()
            period = (fact.period or "").upper()
            if quarter.startswith("Q") or period.startswith("Q"):
                continue
            by_year[int(fact.fiscal_year)] = (int(fact.fiscal_year), value, fact.id, fact.unit)
        return [by_year[year] for year in sorted(by_year)]

    @staticmethod
    def _cagr(points: list[tuple[int, float, int, str]]) -> float | None:
        if len(points) < 2:
            return None
        first, last = points[0], points[-1]
        if first[1] <= 0 or last[1] < 0 or first[0] == last[0]:
            return None
        return (last[1] / first[1]) ** (1 / (last[0] - first[0])) - 1
