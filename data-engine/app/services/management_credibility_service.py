"""Track dated management promises against later reported outcomes."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.models import (
    CallClaim,
    Company,
    Document,
    FinancialFact,
    ManagementPromise,
    Transcript,
)

OPERATORS = {
    ">": lambda actual, target: actual > target,
    ">=": lambda actual, target: actual >= target,
    "<": lambda actual, target: actual < target,
    "<=": lambda actual, target: actual <= target,
    "==": lambda actual, target: actual == target,
}


class ManagementCredibilityService:
    def register(
        self,
        db: Session,
        company: Company,
        *,
        promise: str,
        promise_date: date,
        expected_period: str,
        metric: str | None,
        operator: str | None,
        target_value: Decimal | None,
        unit: str | None,
        source_document_id: int | None = None,
        call_claim_id: int | None = None,
    ) -> ManagementPromise:
        if target_value is not None and operator not in OPERATORS:
            raise ValueError("A numeric promise requires a supported operator")
        if source_document_id is not None:
            # El id llega del cliente: sin comprobarlo, uno inexistente rompía la
            # FK en Postgres (500) y uno de otro usuario o empresa se enlazaba.
            # db.get va acotado por tenant.
            document = db.get(Document, source_document_id)
            if document is None or document.company_id not in (None, company.id):
                raise ValueError("Source document not found for this company")
        row = ManagementPromise(
            company_id=company.id,
            source_document_id=source_document_id,
            call_claim_id=call_claim_id,
            promise=promise.strip(),
            promise_date=promise_date,
            expected_period=expected_period.strip(),
            metric=metric.strip().lower() if metric else None,
            operator=operator,
            target_value=target_value,
            unit=unit,
            status="open",
            evidence=[],
            metadata_={"source": "manual" if call_claim_id is None else "call_claim"},
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def import_call_claims(
        self, db: Session, company: Company
    ) -> list[ManagementPromise]:
        claims = list(
            db.scalars(
                select(CallClaim)
                .join(Transcript, CallClaim.transcript_id == Transcript.id)
                .where(
                    Transcript.company_id == company.id,
                    CallClaim.claim_type.in_(["guidance", "commitment", "target"]),
                )
                .order_by(CallClaim.id)
            ).all()
        )
        created = []
        for claim in claims:
            existing = db.scalar(
                select(ManagementPromise).where(
                    ManagementPromise.call_claim_id == claim.id
                )
            )
            if existing:
                created.append(existing)
                continue
            operator, target = self._target(claim.claim)
            row = ManagementPromise(
                company_id=company.id,
                call_claim_id=claim.id,
                promise=claim.claim,
                promise_date=claim.created_at.date(),
                expected_period=claim.period or "unspecified",
                metric=claim.metric,
                operator=operator,
                target_value=target,
                unit=None,
                status="open",
                evidence=[
                    {
                        "call_claim_id": claim.id,
                        "transcript_id": claim.transcript_id,
                        "speaker": claim.speaker,
                    }
                ],
                metadata_={"source": "call_claim", "speaker_role": claim.speaker_role},
            )
            db.add(row)
            created.append(row)
        db.commit()
        for row in created:
            db.refresh(row)
        return created

    def reconcile(
        self, db: Session, company: Company
    ) -> list[ManagementPromise]:
        promises = list(
            db.scalars(
                select(ManagementPromise)
                .where(ManagementPromise.company_id == company.id)
                .order_by(ManagementPromise.promise_date, ManagementPromise.id)
            ).all()
        )
        for promise in promises:
            if not promise.metric:
                continue
            statement = select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == promise.metric,
            )
            year_match = re.search(r"(?:19|20)\d{2}", promise.expected_period)
            if year_match:
                year = int(year_match.group(0))
                normalized_period = re.sub(
                    r"[^A-Z0-9]", "", promise.expected_period.upper()
                )
                quarter_match = re.search(r"Q[1-4]", normalized_period)
                if quarter_match:
                    # Hechos trimestrales ingeridos desde 10-Q llevan
                    # fiscal_year NULL y el año solo en period '<end>:Qn';
                    # exigir fiscal_year == año los dejaria irreconciliables.
                    statement = statement.where(
                        FinancialFact.fiscal_quarter == quarter_match.group(0),
                        or_(
                            FinancialFact.fiscal_year == year,
                            FinancialFact.period.like(f"{year}-%"),
                        ),
                    )
                elif "FY" in normalized_period:
                    statement = statement.where(
                        FinancialFact.fiscal_year == year
                    )
                    # An annual promise must not be reconciled against a later
                    # quarterly observation from the same fiscal year.
                    statement = statement.where(
                        or_(
                            FinancialFact.fiscal_quarter == "FY",
                            FinancialFact.fiscal_quarter.is_(None),
                        )
                    )
            else:
                statement = statement.where(
                    FinancialFact.period == promise.expected_period
                )
            actual = db.scalar(
                statement.order_by(desc(FinancialFact.created_at)).limit(1)
            )
            if actual is None:
                continue
            promise.actual_fact_id = actual.id
            promise.actual_value = actual.value
            promise.verified_at = datetime.now(UTC)
            if promise.target_value is None or promise.operator not in OPERATORS:
                promise.status = "outcome_recorded"
            else:
                met = OPERATORS[promise.operator](actual.value, promise.target_value)
                if met:
                    promise.status = "met"
                else:
                    distance = abs(actual.value - promise.target_value)
                    tolerance = abs(promise.target_value) * Decimal("0.05")
                    promise.status = "partial" if distance <= tolerance else "missed"
            promise.evidence = [
                *(promise.evidence or []),
                {
                    "financial_fact_id": actual.id,
                    "period": actual.period,
                    "source_type": actual.source_type,
                    "actual_value": str(actual.value),
                },
            ]
        db.commit()
        for promise in promises:
            db.refresh(promise)
        return promises

    def set_explanation(
        self, db: Session, promise: ManagementPromise, explanation: str
    ) -> ManagementPromise:
        promise.management_explanation = explanation.strip()
        db.commit()
        db.refresh(promise)
        return promise

    def dashboard(self, db: Session, company: Company) -> dict[str, Any]:
        promises = list(
            db.scalars(
                select(ManagementPromise)
                .where(ManagementPromise.company_id == company.id)
                .order_by(desc(ManagementPromise.promise_date))
            ).all()
        )
        resolved = [row for row in promises if row.status in {"met", "partial", "missed"}]
        score = (
            sum(1 if row.status == "met" else 0.5 if row.status == "partial" else 0 for row in resolved)
            / len(resolved)
            if resolved
            else None
        )
        return {
            "ticker": company.ticker,
            "score": score,
            "grade": (
                "high" if score is not None and score >= 0.8 else
                "mixed" if score is not None and score >= 0.5 else
                "low" if score is not None else "insufficient_history"
            ),
            "counts": {
                "total": len(promises),
                "open": sum(row.status == "open" for row in promises),
                "met": sum(row.status == "met" for row in promises),
                "partial": sum(row.status == "partial" for row in promises),
                "missed": sum(row.status == "missed" for row in promises),
            },
            "promises": [self.payload(row) for row in promises],
            "method": "resolved promises: met=1, partial=0.5, missed=0",
        }

    @staticmethod
    def payload(row: ManagementPromise) -> dict[str, Any]:
        return {
            "id": row.id,
            "company_id": row.company_id,
            "source_document_id": row.source_document_id,
            "call_claim_id": row.call_claim_id,
            "promise": row.promise,
            "promise_date": row.promise_date,
            "expected_period": row.expected_period,
            "metric": row.metric,
            "operator": row.operator,
            "target_value": row.target_value,
            "unit": row.unit,
            "actual_fact_id": row.actual_fact_id,
            "actual_value": row.actual_value,
            "status": row.status,
            "management_explanation": row.management_explanation,
            "verified_at": row.verified_at,
            "evidence": row.evidence,
        }

    @staticmethod
    def _target(text: str) -> tuple[str | None, Decimal | None]:
        match = re.search(
            r"(at least|more than|above|up to|less than|below|approximately|about)?\s*"
            r"([$€£]?\s*\d+(?:\.\d+)?)",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None, None
        qualifier = (match.group(1) or "approximately").lower()
        operator = (
            ">=" if qualifier in {"at least", "more than", "above"} else
            "<=" if qualifier in {"up to", "less than", "below"} else
            "=="
        )
        numeric = re.sub(r"[^0-9.]", "", match.group(2))
        return operator, Decimal(numeric)
