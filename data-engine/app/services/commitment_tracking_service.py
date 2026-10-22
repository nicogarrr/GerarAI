"""Comprobaciones con fuente y notas privadas de compromisos.

Reglas:
- met / partially_met / not_met exigen evidence_url (https) Y evidence_excerpt: un
  enlace sin contenido que pruebe el criterio no es cumplimiento.
- unknown / not_verifiable / insufficient_evidence solo piden resumen.
- Nada cambia ManagementPromise.status ni se ejecuta solo: lo registra una persona.
- Plazo vencido sin comprobacion = "overdue_unverified", nunca "no cumplido".
- Las notas son privadas: se filtran por owner_user_id (ademas del tenant).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.entities import (
    CHECK_OUTCOMES,
    ManagementPromise,
    ManagementPromiseCheck,
    ManagementPromiseNote,
)

EVIDENCE_REQUIRED = {"met", "partially_met", "not_met"}


class CommitmentTrackingError(ValueError):
    pass


def due_state(promise: ManagementPromise, checks: list[ManagementPromiseCheck], today: date) -> str:
    """no_due_date | pending | overdue_unverified | checked."""
    if any(c.outcome in EVIDENCE_REQUIRED for c in checks):
        return "checked"
    if promise.due_date is None:
        return "no_due_date"
    return "overdue_unverified" if promise.due_date < today else "pending"


class CommitmentTrackingService:
    def add_check(
        self,
        db: Session,
        promise: ManagementPromise,
        *,
        outcome: str,
        checked_on: date,
        summary: str = "",
        evidence_url: str | None = None,
        evidence_date: date | None = None,
        evidence_excerpt: str | None = None,
        user_id: str | None = None,
    ) -> ManagementPromiseCheck:
        if outcome not in CHECK_OUTCOMES:
            raise CommitmentTrackingError("Resultado no valido")
        if promise.status == "candidate":
            raise CommitmentTrackingError(
                "Revisa primero el candidato (cita, contexto, fecha, fuente) y pasalo a seguimiento"
            )
        url = (evidence_url or "").strip() or None
        excerpt = (evidence_excerpt or "").strip() or None
        if url and not url.startswith("https://"):
            raise CommitmentTrackingError("La evidencia debe ser una URL https")
        if outcome in EVIDENCE_REQUIRED and not (url and excerpt):
            raise CommitmentTrackingError(
                "Cumplido, parcial o no cumplido exigen URL de evidencia y extracto que pruebe el criterio"
            )
        if outcome in EVIDENCE_REQUIRED and not (promise.fulfillment_criteria or "").strip():
            raise CommitmentTrackingError(
                "Define primero el criterio de cumplimiento del compromiso"
            )
        if outcome not in EVIDENCE_REQUIRED and not summary.strip():
            raise CommitmentTrackingError("Indica por que no se puede concluir (resumen)")
        row = ManagementPromiseCheck(
            promise_id=promise.id,
            checked_on=checked_on,
            outcome=outcome,
            summary=summary.strip(),
            evidence_url=url,
            evidence_date=evidence_date,
            evidence_excerpt=excerpt[:2000] if excerpt else None,
            created_by_user_id=user_id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def review_candidate(
        self,
        db: Session,
        promise: ManagementPromise,
        *,
        fulfillment_criteria: str,
        due_date: date | None,
        confirmed_source_checked: bool,
        user_id: str | None,
    ) -> ManagementPromise:
        """candidate -> open por declaracion EXPLICITA de la persona que reviso cita/contexto/fuente.

        No verifica nada por si mismo: deja constancia de quien declaro y cuando.
        """
        if promise.status != "candidate":
            raise CommitmentTrackingError("Solo se revisan candidatos sugeridos")
        if not confirmed_source_checked:
            raise CommitmentTrackingError(
                "Confirma que has revisado cita, contexto, fecha y fuente en el documento original"
            )
        criteria = fulfillment_criteria.strip()
        if len(criteria) < 10:
            raise CommitmentTrackingError("Define un criterio de cumplimiento concreto")
        from datetime import UTC, datetime

        promise.fulfillment_criteria = criteria
        if due_date is not None:
            promise.due_date = due_date
            meta_due = "declared_by_user"
        else:
            meta_due = (promise.metadata_ or {}).get("due_basis", "none")
        promise.status = "open"
        promise.status_reason = "Revisado por una persona: criterio declarado por el usuario, sin verificacion automatica."
        promise.metadata_ = {
            **(promise.metadata_ or {}),
            "reviewed_by_user_id": user_id,
            "reviewed_at": datetime.now(UTC).isoformat(),
            "review_kind": "user_declared",
            "due_basis": meta_due,
        }
        db.commit()
        db.refresh(promise)
        return promise

    def checks(self, db: Session, promise: ManagementPromise) -> list[ManagementPromiseCheck]:
        return list(
            db.scalars(
                select(ManagementPromiseCheck)
                .where(ManagementPromiseCheck.promise_id == promise.id)
                .order_by(desc(ManagementPromiseCheck.checked_on), desc(ManagementPromiseCheck.id))
            ).all()
        )

    def add_note(
        self, db: Session, promise: ManagementPromise, *, user_id: str, body: str
    ) -> ManagementPromiseNote:
        text = body.strip()
        if not text:
            raise CommitmentTrackingError("La nota esta vacia")
        row = ManagementPromiseNote(promise_id=promise.id, owner_user_id=user_id, body=text[:5000])
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def notes(self, db: Session, promise: ManagementPromise, *, user_id: str) -> list[ManagementPromiseNote]:
        return list(
            db.scalars(
                select(ManagementPromiseNote)
                .where(
                    ManagementPromiseNote.promise_id == promise.id,
                    ManagementPromiseNote.owner_user_id == user_id,
                )
                .order_by(desc(ManagementPromiseNote.id))
            ).all()
        )

    @staticmethod
    def check_payload(row: ManagementPromiseCheck) -> dict[str, Any]:
        return {
            "id": row.id,
            "promise_id": row.promise_id,
            "checked_on": row.checked_on,
            "outcome": row.outcome,
            "summary": row.summary,
            "evidence_url": row.evidence_url,
            "evidence_date": row.evidence_date,
            "evidence_excerpt": row.evidence_excerpt,
            "declared_by_user_id": row.created_by_user_id,
            "declared_at": row.created_at,
            "verification": "user_declared_not_independently_verified",
        }

    @staticmethod
    def note_payload(row: ManagementPromiseNote) -> dict[str, Any]:
        return {"id": row.id, "promise_id": row.promise_id, "body": row.body, "created_at": row.created_at}
