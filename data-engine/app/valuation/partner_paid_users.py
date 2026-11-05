"""Partner-line paid subscriber scenarios without counting activations as payers.

Addressable units are subscription lines, not unique people. Partner pools
must be disjoint (MVNO/reseller overlap requires upstream reconciliation).
A comparable paid-penetration assumption must identify payer/eligible line
counts for the SAME period/population and a source for transferring that
rate to the partner. Unique connections, compatible devices, beta activations
and free included service cannot establish a paid attach rate.
When the comparable denominator's measurement date is declared, it must sit
inside the comparable period: a numerator from one period cannot be divided
by a denominator from another. When a disjoint pool declares a sourced total,
the partner rows must reconcile with it exactly: components measured under
different scopes must not be summed.
"""
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class PartnerPaidInput:
    partner: str
    disjoint_pool: str
    eligible_lines: Decimal
    eligibility_date: date
    eligible_source: str
    eligible_citation: str
    paid_comparable_lines: Decimal
    comparable_eligible_lines: Decimal
    comparable_period_start: date
    comparable_period_end: date
    comparable_metric: str
    comparable_source: str
    comparable_citation: str
    transfer_rationale: str
    transfer_source: str
    published: date
    comparable_eligible_as_of: date | None = None
    declared_pool_total_lines: Decimal | None = None
    declared_pool_total_source: str = ""


def partner_paid_users(rows: list[PartnerPaidInput], *, as_of: date, scenario: str,
                       forecast_year: int, pool_reconciliation_source: str) -> dict:
    """Sum eligible lines times a demonstrated paid-line attach rate.

    No growth, migration, service availability, market-share or free-to-paid
    conversion is inferred. These belong in the sourced eligible-line pool.
    Calculated values are scenarios, not demonstrated ASTS subscriptions.
    """
    out = {"status": "missing", "paid_subscription_lines": None,
           "scenario": scenario, "forecast_year": forecast_year,
           "inputs": [asdict(r) for r in rows], "components": [],
           "limitations": ["subscription_lines_not_unique_people", "not_capacity_or_revenue_forecast",
                            "comparable_transfer_is_an_assumption"]}
    if not rows or not pool_reconciliation_source:
        return {**out, "reason": "explicit_disjoint_partner_pool_reconciliation_required"}
    if scenario not in {"bear", "base", "bull"} or forecast_year < as_of.year:
        return {**out, "status": "invalid"}
    pools = [r.disjoint_pool for r in rows]
    partners = [r.partner for r in rows]
    if len(set(pools)) != len(pools) or len(set(partners)) != len(partners):
        return {**out, "status": "invalid", "reason": "overlapping_partner_pools"}
    declared = next((r for r in rows if r.declared_pool_total_lines is not None), None)
    if declared is not None:
        if any(r.declared_pool_total_lines != declared.declared_pool_total_lines
               for r in rows if r.declared_pool_total_lines is not None):
            return {**out, "status": "invalid",
                    "reason": "declared_pool_total_disagreement"}
        if (not declared.declared_pool_total_source.startswith("https://")
                or sum(r.eligible_lines for r in rows) != declared.declared_pool_total_lines):
            return {**out, "status": "invalid",
                    "reason": "pool_components_do_not_reconcile_declared_total"}
    total = Decimal(0)
    for r in rows:
        if (r.comparable_eligible_as_of is not None
                and not (r.comparable_period_start
                         <= r.comparable_eligible_as_of
                         <= r.comparable_period_end)):
            return {**out, "status": "invalid",
                    "reason": "comparable_denominator_period_mismatch"}
        vals = (r.eligible_lines, r.paid_comparable_lines, r.comparable_eligible_lines)
        if (not all(v.is_finite() for v in vals) or r.eligible_lines < 0
                or r.paid_comparable_lines < 0 or r.comparable_eligible_lines <= 0
                or r.paid_comparable_lines > r.comparable_eligible_lines
                or r.comparable_metric != "paid_subscription_lines"
                or r.comparable_period_start >= r.comparable_period_end
                or r.published > as_of or r.eligibility_date > as_of
                or r.comparable_period_end > r.published
                or not all((r.partner, r.disjoint_pool, r.eligible_citation.strip(),
                            r.comparable_citation.strip(), r.transfer_rationale.strip()))
                or not all(s.startswith("https://") for s in
                           (r.eligible_source, r.comparable_source, r.transfer_source))):
            return {**out, "status": "invalid", "reason": "paid_comparable_or_source_not_demonstrated"}
        attach = r.paid_comparable_lines/r.comparable_eligible_lines
        value = r.eligible_lines*attach
        total += value
        out["components"].append({"partner": r.partner, "paid_attach_rate": attach,
                                  "paid_subscription_lines": value})
    return {**out, "status": "orientation", "paid_subscription_lines": total,
            "pool_reconciliation_source": pool_reconciliation_source}
