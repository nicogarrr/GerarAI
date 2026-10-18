"""Build a temporally coherent financial snapshot for valuation inputs.

Independent per-metric "latest" queries can mix FY revenue with TTM FCF and
stale shares. This builder anchors on a primary income-statement period and
only accepts companion facts from the same economic snapshot (or a compatible
balance-sheet instant).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact

# Income-statement style metrics: flows over a period. They must share the
# anchor's period, otherwise a 12-month revenue gets divided by a 9-month OCF.
DURATION_METRICS = (
    "revenue",
    "free_cash_flow",
    "fcf_margin",
    "revenue_growth",
    "operating_cash_flow",
    "capital_expenditure",
)
# Balance-sheet style metrics: point-in-time instants.
INSTANT_METRICS = (
    "net_debt",
    "shares_diluted",
    "cash_and_equivalents",
    "total_debt",
)
# The DCF equity bridge is EV - net_debt. A missing net_debt is NOT zero debt:
# it is an unknown that must block the valuation instead of inventing equity.
# Presence + finiteness is the requirement; positivity is NOT, because a
# negative net_debt is net cash and a perfectly valid (and bullish) input.
REQUIRED_FOR_DCF = ("revenue", "shares_diluted", "net_debt")
# Metrics used as a denominator or a scale, which must be strictly positive.
POSITIVE_REQUIRED_FOR_DCF = ("revenue", "shares_diluted")


@dataclass
class FinancialSnapshot:
    as_of_period: str | None = None
    fiscal_year: int | None = None
    fiscal_quarter: str | None = None
    period_type: str | None = None  # FY | Q | TTM
    income_statement: str | None = None
    balance_sheet: str | None = None
    shares_period: str | None = None
    facts: dict[str, FinancialFact] = field(default_factory=dict)
    missing_inputs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    coherent: bool = False
    # metric -> ids of the persisted facts it was derived from (e.g. net_debt
    # = total_debt - cash_and_equivalents). Derived facts are not persisted.
    derived: dict[str, list[int]] = field(default_factory=dict)

    def value(self, metric: str) -> float | None:
        """Return a finite float, or ``None``.

        A stored ``NaN``/``inf`` (allowed by ``Numeric(24, 6)`` in Postgres) is
        treated as a missing input instead of poisoning the whole valuation:
        every downstream clamp in this package is transparent to NaN.
        """
        fact = self.facts.get(metric)
        if fact is None:
            return None
        value = float(fact.value)
        if not math.isfinite(value):
            return None
        return value

    def fact_ids(self) -> dict[str, int | None]:
        return {metric: fact.id for metric, fact in self.facts.items()}

    def periods(self) -> dict[str, str | None]:
        return {metric: fact.period for metric, fact in self.facts.items()}


def _period_type(period: str | None, fiscal_quarter: str | None) -> str:
    text = (period or "").upper()
    if "TTM" in text:
        return "TTM"
    if fiscal_quarter and fiscal_quarter.upper() not in {"FY", "ANNUAL", ""}:
        return "Q"
    if text.startswith("Q") or "Q1" in text or "Q2" in text or "Q3" in text or "Q4" in text:
        return "Q"
    return "FY"


def _facts_for_metric(db: Session, company_id: int, metric: str) -> list[FinancialFact]:
    return list(
        db.scalars(
            select(FinancialFact)
            .where(FinancialFact.company_id == company_id, FinancialFact.metric == metric)
            .order_by(
                FinancialFact.fiscal_year.desc().nullslast(),
                desc(FinancialFact.created_at),
            )
        ).all()
    )


def _missing_without_revenue_anchor(
    db: Session, company_id: int
) -> tuple[list[str], list[str]]:
    """Entradas genuinamente ausentes cuando falta el ancla de revenue.

    QA datos (ASML, 2026-10-18): el corte temprano declaraba ausentes
    shares_diluted y FCF sin comprobarlo, y shares_diluted existia en DB
    (la ficha mostraba «Acciones diluidas (media) 2025-12-31:FY 388,9 M
    SEC»). Sin ancla de revenue no hay snapshot coherente, pero una entrada
    presente es «no utilizable», no «ausente»: solo se reportan las que
    faltan de verdad y las presentes quedan explicadas en warnings.
    """
    missing = ["revenue"]
    warnings: list[str] = []
    if _facts_for_metric(db, company_id, "shares_diluted"):
        warnings.append(
            "shares_diluted existe en DB pero no es utilizable sin el ancla "
            "de revenue; no se reporta como ausente."
        )
    else:
        missing.append("shares_diluted")
    has_fcf = bool(_facts_for_metric(db, company_id, "free_cash_flow"))
    has_margin = bool(_facts_for_metric(db, company_id, "fcf_margin"))
    if has_fcf or has_margin:
        warnings.append(
            "free_cash_flow/fcf_margin existe en DB pero no es utilizable sin "
            "el ancla de revenue; no se reporta como ausente."
        )
    else:
        missing.append("free_cash_flow_or_fcf_margin")
    return missing, warnings


def _same_duration_period(anchor: FinancialFact, candidate: FinancialFact) -> bool:
    # A TTM anchor is not interchangeable with an FY fact (nor with a quarter):
    # both are "duration" facts but they cover different windows, so pairing
    # them silently mixes a 12-month numerator with a 15-month denominator.
    anchor_kind = _period_type(anchor.period, anchor.fiscal_quarter)
    candidate_kind = _period_type(candidate.period, candidate.fiscal_quarter)
    if anchor_kind != candidate_kind:
        return False
    if anchor.fiscal_year is not None and candidate.fiscal_year is not None:
        if candidate.fiscal_year != anchor.fiscal_year:
            return False
        anchor_q = (anchor.fiscal_quarter or "FY").upper()
        cand_q = (candidate.fiscal_quarter or "FY").upper()
        if anchor_q in {"FY", "ANNUAL"} and cand_q in {"FY", "ANNUAL", ""}:
            return True
        return anchor_q == cand_q
    return (anchor.period or "").upper() == (candidate.period or "").upper()


def _compatible_instant(anchor: FinancialFact, candidate: FinancialFact) -> bool:
    """Balance-sheet / shares may be same FY or a later instant in the same year."""
    if anchor.fiscal_year is None or candidate.fiscal_year is None:
        return (anchor.period or "").upper() == (candidate.period or "").upper()
    if candidate.fiscal_year < anchor.fiscal_year:
        return False
    if candidate.fiscal_year > anchor.fiscal_year + 1:
        return False
    return True


def _pick_matching(
    candidates: list[FinancialFact],
    anchor: FinancialFact,
    *,
    instant: bool,
) -> FinancialFact | None:
    matcher = _compatible_instant if instant else _same_duration_period
    for fact in candidates:
        if matcher(anchor, fact):
            return fact
    return None


class FinancialSnapshotBuilder:
    """Assemble a coherent valuation snapshot from FinancialFact rows."""

    @staticmethod
    def _derive_net_debt(snapshot: FinancialSnapshot, anchor: FinancialFact) -> None:
        """net_debt = total_debt - cash_and_equivalents when both are reported.

        Only when no net_debt fact exists, and only when both inputs are
        persisted facts of the SAME instant period and currency. The result is a
        transient ``derivado`` fact (never added to the session) and the ids of
        its two sources are exposed in ``snapshot.derived``.
        """
        if "net_debt" in snapshot.facts:
            return
        debt = snapshot.facts.get("total_debt")
        cash = snapshot.facts.get("cash_and_equivalents")
        if debt is None or cash is None:
            return
        if (debt.period or "").upper() != (cash.period or "").upper():
            return
        if (debt.unit or "") != (cash.unit or ""):
            return
        try:
            d, c = float(debt.value), float(cash.value)
        except (TypeError, ValueError):
            return
        if not (math.isfinite(d) and math.isfinite(c)):
            return
        # Both inputs must come from the same source document; otherwise the
        # derived fact has no single source and the audit keeps it unsupported.
        shared_source = debt.source_id if debt.source_id == cash.source_id else None
        derived = FinancialFact(
            company_id=debt.company_id,
            source_id=shared_source,
            metric="net_debt",
            value=Decimal(str(d - c)),
            period=debt.period,
            fiscal_year=debt.fiscal_year,
            fiscal_quarter=debt.fiscal_quarter,
            unit=debt.unit,
            source_type="DERIVED",
            is_reported=False,
            is_adjusted=False,
            # Column defaults only apply on INSERT; this fact is transient, so
            # every attribute downstream code reads must be set explicitly.
            confidence=min(
                Decimal(str(debt.confidence if debt.confidence is not None else "0.8")),
                Decimal(str(cash.confidence if cash.confidence is not None else "0.8")),
            ),
        )
        snapshot.facts["net_debt"] = derived
        snapshot.balance_sheet = debt.period
        snapshot.derived["net_debt"] = [i for i in (debt.id, cash.id) if i is not None]

    def build(self, db: Session, company: Company) -> FinancialSnapshot:
        revenue_candidates = _facts_for_metric(db, company.id, "revenue")
        if not revenue_candidates:
            missing, warnings = _missing_without_revenue_anchor(db, company.id)
            return FinancialSnapshot(
                missing_inputs=missing,
                coherent=False,
                warnings=warnings,
            )

        anchor = revenue_candidates[0]
        snapshot = FinancialSnapshot(
            as_of_period=anchor.period,
            fiscal_year=anchor.fiscal_year,
            fiscal_quarter=anchor.fiscal_quarter,
            period_type=_period_type(anchor.period, anchor.fiscal_quarter),
            income_statement=anchor.period,
            facts={"revenue": anchor},
        )

        for metric in DURATION_METRICS:
            if metric == "revenue":
                continue
            match = _pick_matching(_facts_for_metric(db, company.id, metric), anchor, instant=False)
            if match:
                snapshot.facts[metric] = match
            else:
                latest = _facts_for_metric(db, company.id, metric)
                if latest:
                    snapshot.warnings.append(
                        f"{metric} latest period {latest[0].period} does not match "
                        f"anchor {anchor.period}; excluded from snapshot."
                    )

        for metric in INSTANT_METRICS:
            match = _pick_matching(_facts_for_metric(db, company.id, metric), anchor, instant=True)
            if match:
                snapshot.facts[metric] = match
                if metric == "net_debt":
                    snapshot.balance_sheet = match.period
                    if (
                        anchor.fiscal_year is not None
                        and match.fiscal_year is not None
                        and match.fiscal_year != anchor.fiscal_year
                    ):
                        # Cross-period balance sheet: expose it instead of
                        # letting a consumer read it as the anchor's own.
                        snapshot.warnings.append(
                            f"net_debt period {match.period} is a different fiscal year "
                            f"than the income statement anchor {anchor.period}."
                        )
                if metric == "shares_diluted":
                    snapshot.shares_period = match.period
            else:
                latest = _facts_for_metric(db, company.id, metric)
                if latest:
                    snapshot.warnings.append(
                        f"{metric} latest period {latest[0].period} is incompatible "
                        f"with anchor {anchor.period}; excluded from snapshot."
                    )

        self._derive_net_debt(snapshot, anchor)

        missing: list[str] = []
        for metric in REQUIRED_FOR_DCF:
            fact = snapshot.facts.get(metric)
            if fact is None or not math.isfinite(float(fact.value)) or metric in POSITIVE_REQUIRED_FOR_DCF and float(fact.value) <= 0:
                missing.append(metric)

        has_margin = "fcf_margin" in snapshot.facts
        has_fcf = "free_cash_flow" in snapshot.facts
        if not has_margin and not has_fcf:
            missing.append("normalized_fcf_or_fcf_margin")

        snapshot.missing_inputs = missing
        snapshot.coherent = not missing
        return snapshot
