"""Recordatorios de eventos macro (T-24 h y T-1 h) como ResearchAlert enrutable.

Reutiliza el calendario macro oficial (FOMC y BLS) y el outbox de alertas: este
modulo solo persiste la alerta, una vez por evento y ventana. El envio por
Telegram o push sigue el consentimiento por tipo ("macro_event") del pipeline.

Reglas de veracidad:
* Nunca se estima una hora. Si la fuente no publica hora (FOMC), el aviso es
  solo de dia: "manana" u "hoy", sin recordatorio de 1 h.
* Una ventana solo se emite mientras sigue siendo cierta: el aviso de 24 h no
  sale ya dentro de la ultima hora, y nada sale cuando el evento ya paso.
* Cada aviso lleva la fuente y su etiqueta (OFICIAL), como el calendario.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ResearchAlert

VERSION = "macro-event-v1"
ET = ZoneInfo("America/New_York")
ALERT_TYPE = "macro_event"
LEAD_24H = timedelta(hours=24)
LEAD_1H = timedelta(hours=1)


def _start(event: dict[str, Any]) -> tuple[datetime, bool] | None:
    """Inicio del evento en UTC y si la fuente publica la hora."""
    try:
        day = datetime.strptime(str(event["date"]), "%Y-%m-%d")
    except (KeyError, ValueError):
        return None
    stamp = event.get("time_et")
    if stamp:
        try:
            hour, minute = (int(part) for part in str(stamp).split(":")[:2])
        except ValueError:
            return None
        return day.replace(hour=hour, minute=minute, tzinfo=ET).astimezone(UTC), True
    return day.replace(tzinfo=ET).astimezone(UTC), False


def due_windows(event: dict[str, Any], now: datetime) -> list[str]:
    """Ventanas ("24h", "1h", "day") que corresponde emitir ahora para el evento."""
    parsed = _start(event)
    if parsed is None:
        return []
    start, has_time = parsed
    if has_time:
        if start - LEAD_24H <= now < start - LEAD_1H:
            return ["24h"]
        if start - LEAD_1H <= now < start:
            return ["1h"]
        return []
    # Solo dia: desde 24 h antes del inicio del dia y hasta el final de ese dia.
    if start - LEAD_24H <= now < start + LEAD_24H:
        return ["day"]
    return []


def _when_text(event: dict[str, Any], window: str, now: datetime) -> str:
    start, has_time = _start(event)  # type: ignore[misc]
    if not has_time:
        today = now.astimezone(ET).date()
        return "hoy" if start.astimezone(ET).date() == today else "mañana"
    minutes = max(1, int((start - now).total_seconds() // 60))
    if window == "1h":
        return f"en {minutes} min" if minutes < 60 else "en 1 h"
    return f"en unas {round(minutes / 60)} h"


def _message(event: dict[str, Any], window: str, now: datetime) -> tuple[str, str]:
    when = _when_text(event, window, now)
    stamp = event.get("time_et")
    hora = f"{stamp} (hora de Nueva York)" if stamp else "hora no publicada por la fuente"
    title = f"{event['title']}: {when}"
    lines = [f"{event['title']} el {event['date']}, {hora}."]
    if event.get("detail"):
        lines.append(f"{event['detail']}.")
    lines.append(f"Fuente: {event.get('source', 'desconocida')} ({event.get('label', 'sin etiqueta')}). "
                 f"{event.get('source_url', '')}".strip())
    return title[:300], " ".join(lines)


def emit_macro_reminders(db: Session, events: list[dict[str, Any]], now: datetime | None = None) -> dict:
    """Persiste los recordatorios que toquen; idempotente por evento y ventana."""
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise ValueError("Tenant context required")
    now = (now or datetime.now(UTC)).astimezone(UTC)
    created: list[int] = []
    existing = 0
    for event in events:
        if not event.get("kind") or not event.get("date"):
            continue
        for window in due_windows(event, now):
            fingerprint = f"{VERSION}:{tenant_id}:{event['kind']}:{event['date']}:{window}"
            if db.scalar(select(ResearchAlert.id).where(
                ResearchAlert.tenant_id == tenant_id, ResearchAlert.fingerprint == fingerprint,
            )) is not None:
                existing += 1
                continue
            title, message = _message(event, window, now)
            alert = ResearchAlert(
                tenant_id=tenant_id, company_id=None, severity="medium", status="open",
                alert_type=ALERT_TYPE, title=title, message=message, fingerprint=fingerprint,
                channels=["in_app"], last_triggered_at=now,
                metadata_={"rule_version": VERSION, "macro_kind": event["kind"],
                           "event_date": event["date"], "time_et": event.get("time_et"),
                           "window": window, "source": event.get("source"),
                           "source_url": event.get("source_url"), "label": event.get("label")},
            )
            try:
                with db.begin_nested():
                    db.add(alert)
                    db.flush()
            except IntegrityError:
                existing += 1
                continue
            created.append(alert.id)
    db.commit()
    return {"created": len(created), "existing": existing, "alert_ids": created}
