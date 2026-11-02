"""Close the loop from forecasts and decisions to approved personal lessons."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    DecisionJournalEntry,
    DecisionLesson,
    ExpectationReview,
)

DECISION_ERROR_TAXONOMY = {
    "overestimating_TAM",
    "underestimating_dilution",
    "extrapolating_peak_margin",
    "ignoring_balance_sheet",
    "management_trust_error",
    "valuation_anchoring",
    "position_sizing_error",
    "selling_too_early",
    "ignoring_cyclicality",
    "thesis_drift",
}


class DecisionLearningService:
    def propose_from_reviews(
        self, db: Session, company: Company
    ) -> list[DecisionLesson]:
        reviews = list(
            db.scalars(
                select(ExpectationReview)
                .where(
                    ExpectationReview.company_id == company.id,
                    ExpectationReview.status == "miss",
                )
                .order_by(ExpectationReview.fiscal_year, ExpectationReview.metric)
            ).all()
        )
        created: list[DecisionLesson] = []
        for review in reviews:
            existing = db.scalar(
                select(DecisionLesson).where(
                    DecisionLesson.expectation_review_id == review.id
                )
            )
            if existing:
                created.append(existing)
                continue
            decision = db.scalar(
                select(DecisionJournalEntry)
                .where(DecisionJournalEntry.company_id == company.id)
                .order_by(
                    desc(DecisionJournalEntry.decision_date),
                    desc(DecisionJournalEntry.id),
                )
                .limit(1)
            )
            taxonomy = self._infer_taxonomy(review.metric)
            variance = (
                f"{review.variance} ({review.variance_percent})"
                if review.variance is not None
                else "Actual result did not meet the expected direction"
            )
            lesson = DecisionLesson(
                decision_journal_entry_id=decision.id if decision else None,
                expectation_review_id=review.id,
                company_id=company.id,
                taxonomy=taxonomy,
                expectation=(
                    f"Expected {review.metric}={review.expected_value} "
                    f"for FY{review.fiscal_year}"
                ),
                outcome=(
                    f"Actual {review.metric}={review.actual_value}"
                    if review.actual_value is not None
                    else "Actual unavailable"
                ),
                deviation=variance,
                cause="Requires analyst attribution",
                error=taxonomy,
                lesson=f"Review the {review.metric} assumption before the next decision.",
                future_application=(
                    f"Add an explicit falsification threshold for {review.metric}."
                ),
                evidence=[
                    {
                        "expectation_review_id": review.id,
                        "forecast_id": review.forecast_id,
                        "actual_fact_id": review.actual_fact_id,
                        "actual_metric_id": review.actual_metric_id,
                        "trace": review.trace,
                    }
                ],
                status="proposed",
                metadata_={
                    "generated_by": "decision_learning_v1",
                    "requires_human_approval": True,
                    "proposed_at": datetime.now(UTC).isoformat(),
                },
            )
            db.add(lesson)
            created.append(lesson)
        db.commit()
        for lesson in created:
            db.refresh(lesson)
        return created

    def update(
        self,
        db: Session,
        lesson: DecisionLesson,
        *,
        taxonomy: str,
        cause: str,
        error: str,
        lesson_text: str,
        future_application: str,
    ) -> DecisionLesson:
        if lesson.status == "approved":
            raise ValueError("Approved lessons are immutable; create a new review")
        if taxonomy not in DECISION_ERROR_TAXONOMY:
            raise ValueError("Unsupported decision error taxonomy")
        lesson.taxonomy = taxonomy
        lesson.cause = cause.strip()
        lesson.error = error.strip()
        lesson.lesson = lesson_text.strip()
        lesson.future_application = future_application.strip()
        lesson.status = "proposed"
        db.commit()
        db.refresh(lesson)
        return lesson

    def decide(
        self, db: Session, lesson: DecisionLesson, *, action: str, actor: str
    ) -> DecisionLesson:
        if action not in {"approve", "reject"}:
            raise ValueError("Decision lesson action must be approve or reject")
        # Solo se decide sobre una leccion propuesta (la ficha solo ofrece los
        # botones entonces). Repetir la misma decision no cambia nada; la
        # contraria daba la vuelta a una leccion aprobada «inmutable».
        if lesson.status == ("approved" if action == "approve" else "rejected"):
            return lesson
        if lesson.status == "approved":
            raise ValueError("Approved lessons are immutable; create a new review")
        if lesson.status != "proposed":
            raise ValueError("Only proposed lessons can be approved; edit and save it first")
        if action == "approve":
            incomplete = [
                field
                for field, value in (
                    ("cause", lesson.cause),
                    ("error", lesson.error),
                    ("lesson", lesson.lesson),
                    ("future_application", lesson.future_application),
                )
                if not value.strip() or value == "Requires analyst attribution"
            ]
            if incomplete:
                raise ValueError(
                    f"Complete lesson fields before approval: {', '.join(incomplete)}"
                )
            lesson.status = "approved"
            lesson.metadata_ = {
                **(lesson.metadata_ or {}),
                "approved_by": actor,
                "approved_at": datetime.now(UTC).isoformat(),
            }
            if lesson.decision_journal_entry_id:
                decision = db.get(
                    DecisionJournalEntry, lesson.decision_journal_entry_id
                )
                if decision:
                    decision.status = "reviewed"
        else:
            lesson.status = "rejected"
            lesson.metadata_ = {
                **(lesson.metadata_ or {}),
                "rejected_by": actor,
                "rejected_at": datetime.now(UTC).isoformat(),
            }
        db.commit()
        db.refresh(lesson)
        return lesson

    @staticmethod
    def list(db: Session, company: Company) -> list[DecisionLesson]:
        return list(
            db.scalars(
                select(DecisionLesson)
                .where(DecisionLesson.company_id == company.id)
                .order_by(desc(DecisionLesson.created_at), desc(DecisionLesson.id))
            ).all()
        )

    @staticmethod
    def payload(lesson: DecisionLesson) -> dict[str, Any]:
        return {
            "id": lesson.id,
            "decision_journal_entry_id": lesson.decision_journal_entry_id,
            "expectation_review_id": lesson.expectation_review_id,
            "company_id": lesson.company_id,
            "taxonomy": lesson.taxonomy,
            "expectation": lesson.expectation,
            "outcome": lesson.outcome,
            "deviation": lesson.deviation,
            "cause": lesson.cause,
            "error": lesson.error,
            "lesson": lesson.lesson,
            "future_application": lesson.future_application,
            "evidence": lesson.evidence,
            "status": lesson.status,
            "metadata": lesson.metadata_,
            "created_at": lesson.created_at,
            "updated_at": lesson.updated_at,
        }

    @staticmethod
    def _infer_taxonomy(metric: str) -> str:
        normalized = metric.lower()
        if "share" in normalized or "dilution" in normalized:
            return "underestimating_dilution"
        if "margin" in normalized:
            return "extrapolating_peak_margin"
        if any(token in normalized for token in ("debt", "cash", "liquidity")):
            return "ignoring_balance_sheet"
        if any(token in normalized for token in ("market_size", "tam", "revenue")):
            return "overestimating_TAM"
        return "thesis_drift"
