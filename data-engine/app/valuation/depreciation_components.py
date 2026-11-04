"""Disjoint D&A components for IFRS: impairment and leases stay separate.

Values are positive expense magnitudes, in one declared currency/scale/period.
Absence is never zero. The caller supplies only disjoint components, not a
reported aggregate alongside its children. No maintenance-capex estimate here.
"""
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ExpenseComponent:
    kind: str
    value: Decimal
    period_start: date
    period_end: date
    currency: str
    scale: int
    scope: str
    published: date
    source_url: str
    citation: str


REQUIRED = frozenset({"ppe_depreciation", "intangible_amortization", "rou_depreciation"})
OPTIONAL = frozenset({"impairment"})


def depreciation_components(rows: list[ExpenseComponent], *, as_of: date) -> dict:
    """Return ex-ROU D&A only when all required categories are explicit.

    Impairment can be unknown without blocking D&A, but then total noncash
    expense remains N/D. Zero impairment must be explicitly sourced.
    """
    out = {"status": "missing", "da_ex_rou": None, "da_including_rou": None,
           "impairment": None, "total_noncash": None,
           "inputs": [asdict(row) for row in rows],
           "limitations": ["not_a_maintenance_capex_estimate", "lease_cash_flow_policy_required"]}
    if not rows:
        return out
    kinds = [row.kind for row in rows]
    anchor = rows[0]
    if (len(set(kinds)) != len(kinds) or set(kinds) - REQUIRED - OPTIONAL
            or any(not row.value.is_finite() or row.value < 0 or row.scale <= 0
                   or row.period_start >= row.period_end
                   or row.published < row.period_end or row.published > as_of or not row.source_url.startswith("https://")
                   or not row.citation.strip() or not row.scope or not row.currency
                   or (row.period_start, row.period_end, row.currency, row.scale, row.scope) !=
                      (anchor.period_start, anchor.period_end, anchor.currency, anchor.scale, anchor.scope)
                   for row in rows)):
        return {**out, "status": "invalid"}
    missing = sorted(REQUIRED-set(kinds))
    if missing:
        return {**out, "missing": missing}
    values = {row.kind: row.value*row.scale for row in rows}
    da = values["ppe_depreciation"] + values["intangible_amortization"]
    total_da = da+values["rou_depreciation"]
    impairment = values.get("impairment")
    return {**out, "status": "ok", "da_ex_rou": da, "da_including_rou": total_da,
            "impairment": impairment, "currency": anchor.currency,
            "total_noncash": total_da+impairment if impairment is not None else None}
