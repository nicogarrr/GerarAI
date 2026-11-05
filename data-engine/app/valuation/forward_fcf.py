"""Pure forward FCF exit-multiple scenarios, separate from the DCF engine.

Enterprise FCF implies EV/FCF and WACC, equity FCF implies P/FCF and Ke.
Net debt is a present-day bridge AFTER discounting enterprise value, never
subtracted from a future equity value. Callers own verified public inputs.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class ForwardScenario:
    name: str
    forward_fcf: Decimal
    exit_multiple: Decimal
    discount_rate: Decimal
    years: int
    shares: Decimal
    currency: str
    basis: str  # enterprise | equity
    net_debt: Decimal | None
    as_of: date
    evidence: dict[str, str]  # input name -> source/reference (or explicit assumption)


def value_forward_scenario(s: ForwardScenario) -> dict:
    """Value an N+2/N+3 exit multiple, without inventing missing inputs.

    >80x forward FCF is returned as an unpublishable orientation with a warning,
    not an unqualified target. Hard-invalid values produce no valuation.
    """
    result = {"name": s.name, "status": "invalid", "publishable": False,
              "value_per_share": None, "warnings": [], "missing": [],
              "interim_cashflows_included": False,
              "limitation": "Exit-value-only cross-check; no interim distributions are added.",
              "inputs": {"forward_fcf": str(s.forward_fcf), "exit_multiple": str(s.exit_multiple),
                         "discount_rate": str(s.discount_rate), "years": s.years,
                         "shares": str(s.shares), "currency": s.currency, "basis": s.basis,
                         "net_debt": str(s.net_debt) if s.net_debt is not None else None,
                         "as_of": s.as_of.isoformat(), "evidence": dict(s.evidence)}}
    required = ["forward_fcf", "exit_multiple", "discount_rate", "shares"]
    if s.basis == "enterprise":
        required.append("net_debt")
    result["missing"] = [key for key in required if not s.evidence.get(key)]
    if s.basis == "enterprise" and s.net_debt is None:
        result["missing"].append("net_debt_value")
    if result["missing"]:
        result["status"] = "missing"
        return result
    try:
        fcf, multiple, rate, shares = (Decimal(str(v)) for v in
                                      (s.forward_fcf, s.exit_multiple, s.discount_rate, s.shares))
        debt = Decimal(str(s.net_debt)) if s.net_debt is not None else Decimal(0)
    except (InvalidOperation, ValueError):
        return result
    if (any(not v.is_finite() for v in (fcf, multiple, rate, shares, debt))
            or fcf <= 0 or multiple <= 0 or shares <= 0 or not 0 < rate <= 1
            or type(s.years) is not int or s.years not in (2, 3)
            or s.basis not in {"enterprise", "equity"} or s.currency not in {"USD", "EUR", "GBP"}
            or (s.basis == "equity" and s.net_debt is not None)):
        return result
    future_value = fcf * multiple
    present_value = future_value / (1 + rate) ** s.years
    equity_value = present_value - debt if s.basis == "enterprise" else present_value
    if equity_value <= 0:
        result["warnings"].append("nonpositive_equity_value")
        return result
    if multiple > 80:
        result["warnings"].append("forward_fcf_multiple_above_80_requires_support")
    result.update(status="orientation" if result["warnings"] else "ok",
                  publishable=not result["warnings"], value_per_share=equity_value / shares,
                  future_capitalized_value=future_value, present_capitalized_value=present_value,
                  equity_value=equity_value,
                  method="EV_FCF_discounted_at_WACC" if s.basis == "enterprise" else "P_FCF_discounted_at_Ke")
    return result


def value_forward_scenarios(scenarios: list[ForwardScenario]) -> dict:
    """Keep all three scenarios visible; never repair or reorder their values."""
    if len(scenarios) != 3 or {s.name for s in scenarios} != {"bear", "base", "bull"}:
        return {"status": "invalid", "reason": "exactly_bear_base_bull_required", "scenarios": []}
    if len({(s.currency, s.basis, s.as_of, s.years, str(s.shares), str(s.net_debt)) for s in scenarios}) != 1:
        return {"status": "invalid", "reason": "incomparable_scenario_bases", "scenarios": []}
    rows = {s.name: value_forward_scenario(s) for s in scenarios}
    values = [rows[k]["value_per_share"] for k in ("bear", "base", "bull")]
    valid = all(v is not None for v in values)
    ordered = valid and values[0] <= values[1] <= values[2]
    return {"status": "ok" if ordered else "invalid", "reason": None if ordered else "missing_or_unordered_values",
            "publishable": bool(ordered and all(r["publishable"] for r in rows.values())),
            "scenarios": [rows[k] for k in ("bear", "base", "bull")]}
