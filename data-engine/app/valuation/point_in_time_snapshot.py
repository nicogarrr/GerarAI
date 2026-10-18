"""Financial snapshot restricted to what was public on ``as_of``.

``FinancialSnapshotBuilder`` answers "what is the latest coherent set of facts".
That is the right question for a live valuation and the wrong one for a replay:
on 2025-06-30 it would hand you the FY2025 accounts filed in 2026 and call the
result a valuation. This module answers "what did an analyst standing on
``as_of`` actually have", and refuses to guess when it cannot prove an input was
public.

It is a deliberate near-mirror of the base builder rather than a parameter on
it: the coherence rules (anchor period, duration vs instant companions) are
reused by import, and only the *candidate query* differs. Editing the shared
``financial_snapshot.py`` to add an ``as_of`` parameter would work, but that file
is loaded by the live valuation path of every other consumer, and a replay-only
filter silently applied there would turn real valuations into abstentions. The
drift risk of mirroring is covered by
``tests/test_thesis_backtest_service.py::test_pit_builder_matches_base_when_nothing_is_filtered``,
which asserts both builders agree once no fact is out of window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact
from app.valuation.financial_snapshot import (
    DURATION_METRICS,
    INSTANT_METRICS,
    POSITIVE_REQUIRED_FOR_DCF,
    REQUIRED_FOR_DCF,
    FinancialSnapshot,
    _facts_for_metric,
    _period_type,
    _pick_matching,
)
from app.valuation.period_bounds import (
    KnowledgeBounds,
    assert_knowledge_no_lookahead,
    knowledge_bounds,
)


@dataclass
class FactVerdict:
    """Why one stored fact was kept or dropped for a given ``as_of``."""

    fact_id: int
    metric: str
    bounds: KnowledgeBounds
    usable: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "fact_id": self.fact_id,
            "metric": self.metric,
            "usable": self.usable,
            "reason": self.reason,
            **self.bounds.as_dict(),
        }


@dataclass
class PITAudit:
    """Full disclosure of what the replay could and could not see."""

    as_of: date
    kept: list[FactVerdict] = field(default_factory=list)
    dropped_future: list[FactVerdict] = field(default_factory=list)
    unverifiable: list[FactVerdict] = field(default_factory=list)

    @property
    def lookahead_violations(self) -> list[str]:
        """One line per fact used or offered whose knowledge date is past ``as_of``."""
        return [
            f"{item.metric} (fact {item.fact_id}): {item.reason}"
            for item in self.dropped_future
        ]

    @property
    def unverifiable_inputs(self) -> list[str]:
        """Inputs excluded because no honest knowledge date could be derived."""
        return [
            f"{item.metric} (fact {item.fact_id}): {item.reason}"
            for item in self.unverifiable
        ]

    def as_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of.isoformat(),
            "kept": [item.as_dict() for item in self.kept],
            "dropped_future": [item.as_dict() for item in self.dropped_future],
            "unverifiable": [item.as_dict() for item in self.unverifiable],
        }


class PointInTimeSnapshotBuilder:
    """Assemble a coherent snapshot from facts public on or before ``as_of``."""

    def __init__(self, *, as_of: date) -> None:
        self.as_of = as_of
        self.audit = PITAudit(as_of=as_of)

    # ------------------------------------------------------------------ audit

    def verdict(self, fact: FinancialFact, published_on: date | None) -> FactVerdict:
        """Classify one fact against the cutoff. Pure: no state mutated."""
        bounds = knowledge_bounds(
            period=fact.period,
            fiscal_year=fact.fiscal_year,
            fiscal_quarter=fact.fiscal_quarter,
            published_at=published_on,
        )
        if bounds.unverifiable:
            return FactVerdict(
                fact_id=fact.id,
                metric=fact.metric,
                bounds=bounds,
                usable=False,
                reason=(
                    "sin fecha utilizable (periodo="
                    f"{bounds.period.raw!r}, precision={bounds.period.precision}): "
                    "no se puede probar que fuera publico en la fecha de corte"
                ),
            )
        known_on = bounds.known_on
        assert known_on is not None  # narrowed by unverifiable above
        if known_on > self.as_of:
            return FactVerdict(
                fact_id=fact.id,
                metric=fact.metric,
                bounds=bounds,
                usable=False,
                reason=(
                    f"publicable el {known_on.isoformat()}, despues del corte "
                    f"{self.as_of.isoformat()}"
                ),
            )
        return FactVerdict(
            fact_id=fact.id,
            metric=fact.metric,
            bounds=bounds,
            usable=True,
            reason=f"publicable el {known_on.isoformat()}",
        )

    # ------------------------------------------------------------- candidates

    def _published_dates(self, db: Session, company_id: int) -> dict[int, date | None]:
        """Publication date per source document, in one query.

        A fact whose source has no published_at is unusable in a replay:
        the period end is only a lower bound on when it could have become
        public, so the builder abstains. But we never
        pretend the filing date exists, so the audit shows ``published_on:
        null`` and the cell is flagged as unverifiable-provenance.
        """
        from app.models import Document

        rows = db.execute(
            select(FinancialFact.source_id, Document.published_at)
            .join(Document, Document.id == FinancialFact.source_id, isouter=True)
            .where(FinancialFact.company_id == company_id)
        ).all()
        return {
            source_id: (published_at.date() if published_at else None)
            for source_id, published_at in rows
            if source_id
        }

    def _candidates(
        self,
        db: Session,
        company_id: int,
        metric: str,
        published: dict[int, date | None],
    ) -> list[FinancialFact]:
        """Facts for ``metric`` that were public on or before the cutoff.

        The SQL predicate is a cheap prefilter on the coarse fiscal year only;
        the exact decision is taken in Python by :meth:`verdict`, because the
        period is free text and the publication date lives in another table.
        """
        raw = _facts_for_metric(db, company_id, metric)
        usable: list[FinancialFact] = []
        for fact in raw:
            verdict = self.verdict(fact, published.get(fact.source_id))
            if verdict.usable:
                self.audit.kept.append(verdict)
                usable.append(fact)
            elif verdict.bounds.unverifiable:
                self.audit.unverifiable.append(verdict)
            else:
                self.audit.dropped_future.append(verdict)
        return usable

    # ------------------------------------------------------------------ build

    def build(self, db: Session, company: Company) -> FinancialSnapshot:
        published = self._published_dates(db, company.id)
        revenue_candidates = self._candidates(db, company.id, "revenue", published)
        if not revenue_candidates:
            return FinancialSnapshot(
                missing_inputs=["revenue", "shares_diluted", "free_cash_flow_or_fcf_margin"],
                coherent=False,
                warnings=[
                    f"sin hechos de revenue publicables en {self.as_of.isoformat()}"
                ],
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
            candidates = self._candidates(db, company.id, metric, published)
            match = _pick_matching(candidates, anchor, instant=False)
            if match is not None:
                snapshot.facts[metric] = match
            elif candidates:
                snapshot.warnings.append(
                    f"{metric} latest period {candidates[0].period} does not match "
                    f"anchor {anchor.period}; excluded from snapshot."
                )

        for metric in INSTANT_METRICS:
            candidates = self._candidates(db, company.id, metric, published)
            match = _pick_matching(candidates, anchor, instant=True)
            if match is not None:
                snapshot.facts[metric] = match
                if metric == "net_debt":
                    snapshot.balance_sheet = match.period
                    if (
                        anchor.fiscal_year is not None
                        and match.fiscal_year is not None
                        and match.fiscal_year != anchor.fiscal_year
                    ):
                        snapshot.warnings.append(
                            f"net_debt period {match.period} is a different fiscal year "
                            f"than the income statement anchor {anchor.period}."
                        )
                if metric == "shares_diluted":
                    snapshot.shares_period = match.period
            elif candidates:
                snapshot.warnings.append(
                    f"{metric} latest period {candidates[0].period} is incompatible "
                    f"with anchor {anchor.period}; excluded from snapshot."
                )

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

    def assert_no_lookahead(self, snapshot: FinancialSnapshot | None) -> None:
        """Re-check the facts the snapshot actually kept, using the public guard.

        ``_candidates`` already filtered, so this is a belt-and-braces pass over
        the *selected* rows. It is the assertion a backtest must be able to
        point at: if it ever fires, a fact slipped past the filter.
        """
        if snapshot is None:
            return
        for metric, fact in snapshot.facts.items():
            verdict = next((v for v in self.audit.kept if v.fact_id == fact.id), None)
            bounds = verdict.bounds if verdict else knowledge_bounds(
                period=fact.period,
                fiscal_year=fact.fiscal_year,
                fiscal_quarter=fact.fiscal_quarter,
            )
            try:
                assert_knowledge_no_lookahead(
                    as_of=self.as_of, bounds=bounds, label=f"snapshot.{metric}"
                )
            except Exception as exc:  # noqa: BLE001 - surfaced as a data defect
                raise AssertionError(str(exc)) from exc


__all__ = [
    "FactVerdict",
    "PITAudit",
    "PointInTimeSnapshotBuilder",
]
