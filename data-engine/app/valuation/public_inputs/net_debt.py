"""Pure balance-sheet bridge; callers own retrieval and persistence."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class PublicFact:
    metric: str
    value: Decimal
    unit: str
    period_end: date
    filed: date
    source_url: str
    fact_ref: str
    official: bool = True
    derived: bool = False


def calculate_net_debt(facts: list[PublicFact], *, period_end: date, as_of: date, currency: str) -> dict:
    """Debt - cash - liquid short-term investments, never absence -> zero.

    Total debt takes precedence over its disjoint current/noncurrent parts.
    Missing investments leave the full bridge unknown, while exposing cash-only
    debt separately. No FX conversion, leases assumption or database writes.
    """
    selected = {}
    conflicts = []
    for metric in ("total_debt", "short_term_debt", "long_term_debt", "cash_and_equivalents", "short_term_investments"):
        eligible = [f for f in facts if f.metric == metric and f.period_end == period_end
                    and f.filed <= as_of and f.unit == currency and f.source_url and f.fact_ref]
        if not eligible:
            continue
        latest = max(f.filed for f in eligible)
        candidates = [f for f in eligible if f.filed == latest]
        try:
            values = {Decimal(str(f.value)) for f in candidates}
        except InvalidOperation:
            conflicts.append(metric)
            continue
        if any(not v.is_finite() or v < 0 for v in values) or len(values) != 1:
            conflicts.append(metric)
            continue
        selected[metric] = candidates[0]
    components = []
    missing = []
    debt = selected.get("total_debt")
    if debt is not None:
        debt_value = Decimal(str(debt.value))
        components.append(debt)
    else:
        parts = [selected.get(k) for k in ("short_term_debt", "long_term_debt")]
        if all(p is not None for p in parts):
            debt_value = sum((Decimal(str(p.value)) for p in parts), Decimal(0))
            components.extend(parts)
        else:
            debt_value = None
            missing.append("total_debt_or_complete_components")
    cash = selected.get("cash_and_equivalents")
    investments = selected.get("short_term_investments")
    for key, fact in (("cash_and_equivalents", cash), ("short_term_investments", investments)):
        if fact is None:
            missing.append(key)
        else:
            components.append(fact)
    cash_only = debt_value - Decimal(str(cash.value)) if debt_value is not None and cash else None
    value = cash_only - Decimal(str(investments.value)) if cash_only is not None and investments else None
    if conflicts:
        value = cash_only = None
    return {"status": "conflict" if conflicts else "missing" if missing else "ok",
            "net_debt": value, "net_debt_ex_cash_only": cash_only,
            "currency": currency, "period_end": period_end.isoformat(), "derived": True,
            "missing": missing, "conflicts": conflicts,
            "components": [{"metric": f.metric, "value": str(f.value), "unit": f.unit,
                            "filed": f.filed.isoformat(), "source_url": f.source_url,
                            "fact_ref": f.fact_ref, "official": f.official, "derived": f.derived}
                           for f in components]}


# Only aggregate concepts: aliases are alternatives, never added together.
SEC_BALANCE_CONCEPTS = {
    "total_debt": ("DebtLongtermAndShorttermCombinedAmount",),
    "cash_and_equivalents": ("CashAndCashEquivalentsAtCarryingValue",),
    "short_term_investments": ("ShortTermInvestments", "MarketableSecuritiesCurrent"),
}


def parse_sec_balances(payload: dict, *, source_url: str, as_of: date) -> list[PublicFact]:
    """Parse instant consolidated companyfacts only, retaining accession refs.

    No debt concept means no debt fact, not a zero. Debt securities on the
    asset side never count as borrowing. The caller supplies the fetched URL.
    """
    result = []
    concepts = (payload.get("facts") or {}).get("us-gaap") or {}
    for metric, aliases in SEC_BALANCE_CONCEPTS.items():
        for concept in aliases:
            for unit, entries in (concepts.get(concept, {}).get("units") or {}).items():
                if unit not in {"USD", "EUR", "GBP"}:
                    continue
                for row in entries:
                    if row.get("start") or row.get("form") not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}:
                        continue
                    try:
                        end = date.fromisoformat(row["end"])
                        filed = date.fromisoformat(row["filed"])
                        value = Decimal(str(row["val"]))
                    except (KeyError, ValueError, InvalidOperation):
                        continue
                    if filed > as_of or end > filed or not value.is_finite() or value < 0 or not row.get("accn"):
                        continue
                    result.append(PublicFact(metric, value, unit, end, filed, source_url,
                                             f"{row['accn']}:{concept}:{end.isoformat()}"))
    return result
