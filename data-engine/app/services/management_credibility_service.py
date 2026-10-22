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


MAX_CANDIDATES_PER_COMPANY = 400


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
        quote_literal: str | None = None,
        quote_translation_es: str | None = None,
        speaker: str | None = None,
        speaker_role: str | None = None,
        call_date: date | None = None,
        source_url: str | None = None,
        transcript_locator: str | None = None,
        due_date: date | None = None,
        fulfillment_criteria: str | None = None,
    ) -> ManagementPromise:
        if target_value is not None and operator not in OPERATORS:
            raise ValueError("A numeric promise requires a supported operator")
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
            quote_literal=quote_literal,
            quote_translation_es=quote_translation_es,
            speaker=speaker,
            speaker_role=speaker_role,
            call_date=call_date,
            source_url=source_url,
            transcript_locator=transcript_locator,
            due_date=due_date,
            fulfillment_criteria=fulfillment_criteria,
            # promise_date la da quien registra; si coincide con call_date es la
            # fecha real de la llamada, si no, es la que el usuario introdujo.
            date_basis="call_date" if call_date == promise_date else "user_entered",
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
            # El objetivo numerico NO se autodeduce del texto: la heuristica
            # tomaba el primer numero (p. ej. el ano) como objetivo. Se guarda
            # solo como sugerencia en metadata, sin efecto en la conciliacion.
            suggested_operator, suggested_target = self._target(claim.claim)
            operator, target = None, None
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
                metadata_={
                    "source": "call_claim",
                    "speaker_role": claim.speaker_role,
                    "suggested_target_unverified": (
                        {"operator": suggested_operator, "value": str(suggested_target)}
                        if suggested_target is not None
                        else None
                    ),
                },
                quote_literal=claim.claim,
                speaker=claim.speaker,
                speaker_role=claim.speaker_role,
                # created_at es el alta en BD, no la fecha de la llamada.
                date_basis="registered_at",
            )
            db.add(row)
            created.append(row)
        db.commit()
        for row in created:
            db.refresh(row)
        return created

    def register_extracted_candidates(
        self,
        db: Session,
        company: Company,
        *,
        transcript_text: str,
        call_date: date,
        source_url: str,
        source_check: str = "not_checked",
    ) -> list[ManagementPromise]:
        """Guarda candidatos extraidos (status="candidate", source_status="suggested").

        No guarda el texto de la transcripcion: solo la cita corta, localizador
        versionado, contexto de 80 caracteres y flags. Sin operador/objetivo,
        asi reconcile() nunca los resuelve. Dedup por (empresa, cita literal).
        call_date y source_url los aporta quien llama; no se verifican aqui.
        """
        from app.services.commitment_extraction_service import (
            extract_candidates,
            locator_for,
        )

        # Identidad = (cita, fecha de llamada, fuente): la misma frase en otra
        # llamada o fuente es otro compromiso, no un duplicado.
        existing_rows = db.scalars(
            select(ManagementPromise).where(ManagementPromise.company_id == company.id)
        ).all()
        if sum(row.status == "candidate" for row in existing_rows) >= MAX_CANDIDATES_PER_COMPANY:
            raise ValueError("Limite de candidatos sugeridos alcanzado; revisa o descarta los existentes")
        existing = {
            (row.quote_literal, row.call_date, row.source_url)
            for row in existing_rows
            if row.quote_literal
        }
        created: list[ManagementPromise] = []
        for cand in extract_candidates(transcript_text):
            if (cand.quote_literal, call_date, source_url) in existing:
                continue
            row = ManagementPromise(
                company_id=company.id,
                promise=cand.quote_literal,
                promise_date=call_date,
                expected_period=(
                    str(cand.due_date_hint.year) if cand.due_date_hint else "unknown"
                ),
                status="candidate",
                evidence=[],
                metadata_={
                    "source": "extraction_candidate",
                    "source_status": "suggested",
                    "source_check": source_check,
                    "flags": cand.flags,
                    "due_basis": cand.due_basis,
                    "locator_normalization": cand.normalization,
                    "context_before": cand.context_before,
                    "context_after": cand.context_after,
                },
                quote_literal=cand.quote_literal,
                speaker=cand.speaker,
                speaker_role=cand.speaker_role,
                call_date=call_date,
                source_url=source_url,
                transcript_locator=locator_for(cand),
                due_date=cand.due_date_hint,
                status_reason="Candidato extraido por reglas; sin revisar contra la fuente.",
                date_basis="user_entered",
            )
            db.add(row)
            created.append(row)
            existing.add((cand.quote_literal, call_date, source_url))
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
        # Promesas importadas ANTES de 0078 desde call claims llevan objetivo
        # deducido por heuristica (primer numero) sin procedencia: no entran en
        # la puntuacion para no mostrar credibilidad numerica no fiable.
        legacy = [row for row in promises if self._is_legacy_heuristic(row)]
        legacy_ids = {row.id for row in legacy}
        resolved = [
            row
            for row in promises
            if row.status in {"met", "partial", "missed"} and row.id not in legacy_ids
        ]
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
                "registered": sum(row.status != "candidate" for row in promises),
                "open": sum(row.status == "open" for row in promises),
                "candidate": sum(row.status == "candidate" for row in promises),
                "met": sum(row.status == "met" for row in promises),
                "partial": sum(row.status == "partial" for row in promises),
                "missed": sum(row.status == "missed" for row in promises),
            },
            "legacy_excluded_from_score": len(legacy),
            "promises": self._with_tracking(db, promises),
            "method": "resolved promises: met=1, partial=0.5, missed=0",
        }

    def _with_tracking(self, db: Session, promises: list[ManagementPromise]) -> list[dict[str, Any]]:
        from datetime import date as _date

        from app.models.entities import ManagementPromiseCheck
        from app.services.commitment_tracking_service import CommitmentTrackingService, due_state

        ids = [row.id for row in promises]
        by_promise: dict[int, list] = {}
        if ids:
            for check in db.scalars(
                select(ManagementPromiseCheck)
                .where(ManagementPromiseCheck.promise_id.in_(ids))
                .order_by(desc(ManagementPromiseCheck.checked_on), desc(ManagementPromiseCheck.id))
            ).all():
                by_promise.setdefault(check.promise_id, []).append(check)
        today = _date.today()
        out = []
        for row in promises:
            checks = by_promise.get(row.id, [])
            item = self.payload(row)
            item["due_state"] = due_state(row, checks, today)
            item["checks"] = [CommitmentTrackingService.check_payload(c) for c in checks]
            out.append(item)
        return out

    @staticmethod
    def _is_legacy_heuristic(row: ManagementPromise) -> bool:
        return (
            (row.metadata_ or {}).get("source") == "call_claim"
            and row.date_basis is None
            and row.target_value is not None
        )

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
            "quote_literal": row.quote_literal,
            "quote_translation_es": row.quote_translation_es,
            "speaker": row.speaker,
            "speaker_role": row.speaker_role,
            "call_date": row.call_date,
            "source_url": row.source_url,
            "transcript_locator": row.transcript_locator,
            "due_date": row.due_date,
            "fulfillment_criteria": row.fulfillment_criteria,
            "status_reason": row.status_reason,
            "date_basis": row.date_basis,
            "source_status": (row.metadata_ or {}).get("source_status"),
            "flags": (row.metadata_ or {}).get("flags") or [],
            "source_check": (row.metadata_ or {}).get("source_check"),
            "reviewed_by_user_id": (row.metadata_ or {}).get("reviewed_by_user_id"),
            "reviewed_at": (row.metadata_ or {}).get("reviewed_at"),
            "legacy_heuristic_target": ManagementCredibilityService._is_legacy_heuristic(row),
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
