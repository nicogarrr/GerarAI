import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Claim,
    NewsEvent,
    ResearchAlert,
    ResearchReview,
    ThesisChange,
)
from app.services.notification_service import record_in_app_delivery
from app.services.review_copy import change_type_label, claim_status_label


def _severity(materiality_score: int, negative: bool = False) -> str:
    if materiality_score >= 9 and negative:
        return "critical"
    if materiality_score >= 8:
        return "high"
    if materiality_score >= 5:
        return "medium"
    return "low"


class ReviewAlertService:
    def create_review(
        self,
        db: Session,
        *,
        review_type: str,
        title: str,
        summary: str,
        company_id: int | None,
        materiality_score: int = 5,
        impact_direction: str = "neutral",
        thesis_change_id: int | None = None,
        claim_id: int | None = None,
        news_event_id: int | None = None,
        metadata: dict | None = None,
    ) -> ResearchReview:
        filters = [
            ResearchReview.status.in_(["open", "in_progress"]),
            ResearchReview.company_id == company_id,
            ResearchReview.review_type == review_type,
        ]
        if thesis_change_id is not None:
            filters.append(ResearchReview.thesis_change_id == thesis_change_id)
        elif claim_id is not None:
            filters.append(ResearchReview.claim_id == claim_id)
        elif news_event_id is not None:
            filters.append(ResearchReview.news_event_id == news_event_id)
        existing = db.scalar(select(ResearchReview).where(*filters).limit(1))
        if existing:
            return existing

        # Etiqueta de la bandeja, no auto-aprueba ni oculta tickets.
        try:
            from app.services.jev_gates import TICKET_CRITERIA, mark_only
            mark = mark_only("copilot_ticket", f"{title}\n{summary}",
                "Classify the evidence status for human review; do not verify the source.", TICKET_CRITERIA)
            if mark:
                metadata = {**(metadata or {}), "jev_ticket": mark}
        except Exception:  # noqa: BLE001
            pass
        review = ResearchReview(
            company_id=company_id,
            review_type=review_type,
            status="open",
            priority=_severity(materiality_score, impact_direction == "negative"),
            title=title[:300],
            summary=summary,
            thesis_change_id=thesis_change_id,
            claim_id=claim_id,
            news_event_id=news_event_id,
            metadata_=metadata or {},
        )
        db.add(review)
        db.flush()
        if self._news_already_alerted(db, review_type, company_id, news_event_id):
            # La revision de tesis se crea igual; solo se evita un segundo aviso de la misma noticia.
            return review
        self.emit_alert(
            db,
            company_id=company_id,
            review_id=review.id,
            alert_type=review_type,
            severity=review.priority,
            title=title,
            message=summary,
            fingerprint_parts=[
                review_type,
                str(company_id or ""),
                str(thesis_change_id or ""),
                str(claim_id or ""),
                str(news_event_id or ""),
            ],
            metadata=metadata,
        )
        return review

    @staticmethod
    def _news_already_alerted(
        db: Session, review_type: str, company_id: int | None, news_event_id: int | None
    ) -> bool:
        from app.models.entities import NewsEvent
        from app.services.news_identity import NEWS_ALERT_TYPES, equivalent_news_alert

        if review_type not in NEWS_ALERT_TYPES or news_event_id is None:
            return False
        event = db.get(NewsEvent, news_event_id)
        if event is None:
            return False
        return equivalent_news_alert(
            db, company_id=company_id, url=event.url, title=event.title
        ) is not None

    def create_from_change(
        self,
        db: Session,
        change: ThesisChange,
        *,
        claim_id: int | None = None,
        news_event_id: int | None = None,
        metadata: dict | None = None,
    ) -> ResearchReview | None:
        if not change.requires_review:
            return None
        return self.create_review(
            db,
            review_type=change.change_type,
            title=f"Revisión necesaria: {change_type_label(change.change_type)}",
            summary=change.summary,
            company_id=change.company_id,
            materiality_score=change.materiality_score,
            impact_direction=change.impact_direction,
            thesis_change_id=change.id,
            claim_id=claim_id,
            news_event_id=news_event_id,
            metadata=metadata,
        )

    def create_from_claim(
        self, db: Session, claim: Claim, relation: str, summary: str
    ) -> ResearchReview:
        return self.create_review(
            db,
            review_type=f"claim_{relation}",
            title=f"Afirmación clasificada como {claim_status_label(relation)}",
            summary=summary,
            company_id=claim.company_id,
            materiality_score=claim.materiality_score,
            impact_direction="negative" if relation in {"contradicted", "stale"} else "mixed",
            claim_id=claim.id,
            metadata={"relation": relation},
        )

    def create_from_news(
        self, db: Session, news: NewsEvent, change: ThesisChange
    ) -> ResearchReview | None:
        return self.create_from_change(
            db,
            change,
            news_event_id=news.id,
            metadata={"news_event_id": news.id},
        )

    def emit_alert(
        self,
        db: Session,
        *,
        company_id: int | None,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        fingerprint_parts: list[str],
        review_id: int | None = None,
        channels: list[str] | None = None,
        metadata: dict | None = None,
    ) -> ResearchAlert:
        tenant_id = db.info.get("tenant_id")
        raw = ":".join([str(tenant_id or "legacy"), *fingerprint_parts])
        fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:160]
        existing = db.scalar(
            select(ResearchAlert).where(ResearchAlert.fingerprint == fingerprint)
        )
        now = datetime.now(UTC)
        if existing:
            if existing.status == "resolved":
                existing.status = "open"
                existing.resolved_at = None
            existing.message = message
            existing.severity = severity
            existing.metadata_ = {**(existing.metadata_ or {}), **(metadata or {})}
            # Re-disparo de la misma huella: la hora exhibida debe ser la de
            # este disparo, no la de la creacion de la fila.
            existing.last_triggered_at = now
            return existing
        alert = ResearchAlert(
            company_id=company_id,
            review_id=review_id,
            severity=severity,
            status="open",
            alert_type=alert_type,
            title=title[:300],
            message=message,
            fingerprint=fingerprint,
            channels=channels or self._default_channels(),
            last_triggered_at=now,
            metadata_=metadata or {},
        )
        db.add(alert)
        db.flush()
        record_in_app_delivery(db, alert)
        return alert

    def _default_channels(self) -> list[str]:
        configured = str(
            getattr(get_settings(), "alert_default_channels", "in_app")
        )
        allowed = {"in_app", "email", "push"}
        channels = [
            channel.strip()
            for channel in configured.split(",")
            if channel.strip() in allowed
        ]
        return list(dict.fromkeys(channels)) or ["in_app"]

    def transition_alert(
        self,
        alert: ResearchAlert,
        *,
        action: str,
        actor: str,
        snoozed_until: datetime | None = None,
    ) -> ResearchAlert:
        now = datetime.now(UTC)
        if action == "acknowledge":
            alert.status = "acknowledged"
            alert.acknowledged_at = now
            alert.acknowledged_by = actor
        elif action == "resolve":
            alert.status = "resolved"
            alert.resolved_at = now
        elif action == "snooze":
            # El cliente envia un datetime sin zona (Pydantic no impone tz) y
            # `naive <= aware` lanza TypeError, que el caller solo captura como
            # ValueError: un snooze con fecha sin sufijo Z devolvia 500. Se
            # normaliza asumiendo UTC, que es como se escribe en la app.
            if snoozed_until is not None and snoozed_until.tzinfo is None:
                snoozed_until = snoozed_until.replace(tzinfo=UTC)
            if snoozed_until is None or snoozed_until <= now:
                raise ValueError("snoozed_until must be in the future")
            alert.status = "snoozed"
            alert.snoozed_until = snoozed_until
        elif action == "reopen":
            alert.status = "open"
            alert.resolved_at = None
            alert.snoozed_until = None
        else:
            raise ValueError(f"Unsupported alert action: {action}")
        return alert

    def transition_review(
        self, review: ResearchReview, *, status: str, resolution_notes: str | None
    ) -> ResearchReview:
        review.status = status
        review.resolution_notes = resolution_notes
        if status in {"approved", "dismissed", "resolved"}:
            review.resolved_at = datetime.now(UTC)
        else:
            review.resolved_at = None
        return review
