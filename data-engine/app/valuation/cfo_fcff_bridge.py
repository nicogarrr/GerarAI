"""Pure CFO to pre-financing FCF bridge, never a net-income interest guess.

FCFF = CFO - cash capex + interest deducted in CFO - cash tax shield.
The shield is an explicit sourced assumption/amount, not an automatic tax
rate on net interest expense. US GAAP CFO usually includes cash interest;
IFRS can classify interest in financing. The caller must establish which.
Even then the CFO tax benefit must be removed if it reduced taxes in CFO.
This bridge is not FCFE (net borrowing is excluded) and not issuer-defined
FCF (which may contain accrual adjustments). No annualisation is performed.
"""
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class CashFlowInput:
    key: str
    value: Decimal
    start: date
    end: date
    currency: str
    scale: int
    scope: str
    published: date
    source_url: str
    citation: str


REQUIRED = frozenset({"cfo", "cash_capex", "cash_interest_deducted_in_cfo", "cash_interest_tax_shield"})


def cfo_to_fcff(rows: list[CashFlowInput], *, as_of: date) -> dict:
    out = {"status": "missing", "fcff": None, "inputs": [asdict(row) for row in rows],
           "limitations": ["not_fcfe_or_issuer_defined_fcf", "not_annualized",
                            "no_automatic_tax_shield_estimate"]}
    keys = [row.key for row in rows]
    if not rows:
        return out
    base = rows[0]
    if (len(set(keys)) != len(keys) or set(keys)-REQUIRED
            or any(not r.value.is_finite() or r.scale <= 0 or r.start >= r.end
                   or r.published < r.end or r.published > as_of
                   or not r.source_url.startswith("https://") or not r.citation.strip()
                   or not r.currency or not r.scope
                   or (r.start, r.end, r.currency, r.scale, r.scope) !=
                      (base.start, base.end, base.currency, base.scale, base.scope)
                   or (r.key != "cfo" and r.value < 0) for r in rows)):
        return {**out, "status": "invalid"}
    missing = sorted(REQUIRED-set(keys))
    if missing:
        return {**out, "missing": missing}
    values = {r.key: r.value*r.scale for r in rows}
    interest = values["cash_interest_deducted_in_cfo"]
    shield = values["cash_interest_tax_shield"]
    return {**out, "status": "ok", "fcff": values["cfo"]-values["cash_capex"]+interest-shield,
            "after_tax_interest_addback": interest-shield, "currency": base.currency,
            "formula": "cfo - cash_capex + cash_interest_deducted_in_cfo - cash_interest_tax_shield"}
