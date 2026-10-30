"""Avisos de proximos resultados (tipo Investing) para cartera + watchlist.

Lee las fechas YA refrescadas en ``earnings_dates`` (el refresco vive en
``refresh_earnings_dates``; este modulo nunca llama a fuentes externas) y
emite una alerta ``earnings_reminder`` en tres ventanas: 7 dias, 1 dia y el
propio dia. Cada aviso sale una unica vez por ticker, fecha y ventana
(huella deduplicada) y se despacha por el outbox (in_app / correo SMTP /
Telegram y push con suscripcion "earnings").

Reglas de veracidad (las mismas del calendario de resultados):

* La fecha es la elegida por ``followed_calendar``: la fila ``manual``
  (empresa, enlazada) gana; si no, la automatica mas proxima y fresca.
* Nunca se inventa una hora: solo se muestra la franja (pre/post mercado)
  cuando la fuente la publica (NASDAQ).
* ``confirmed`` es tri-estado y se traduce literal: confirmada, estimada
  (puede cambiar) o "la fuente no lo dice".
* Sin fecha fresca no hay aviso: nunca se proyecta una supuesta.

El "hoy" del aviso se calcula en la zona horaria del mercado del ticker
(cierre de la linea real), no en UTC: una presentacion "manana" en Tokio no
debe avisar un dia antes en Madrid.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AlertDelivery, ResearchAlert
from app.services import earnings_alert_copy
from app.services.earnings_dates_service import (
    followed_calendar,
    followed_companies,
    market_timezone,
)
from app.services.propicks_price_service import yahoo_symbol

logger = logging.getLogger(__name__)

VERSION = "earnings-reminder-v1"
ALERT_TYPE = "earnings_reminder"
_ALLOWED_CHANNELS = ("in_app", "email", "push")
# Ventana (dias hasta la fecha) -> nombre. 0 = el propio dia.
WINDOW_DAYS = {"week": 7, "day": 1, "today": 0}
SEVERITY_BY_WINDOW = {"today": "high", "day": "medium", "week": "low"}
# Maxima antelacion avisada: el horizonte del barrido diario.
HORIZON_DAYS = max(WINDOW_DAYS.values())


def alert_channels(settings: Any) -> list[str]:
    raw = str(getattr(settings, "earnings_alert_channels", "in_app") or "in_app")
    channels = [c.strip() for c in raw.split(",") if c.strip() in _ALLOWED_CHANNELS]
    return list(dict.fromkeys(channels)) or ["in_app"]


def _fingerprint(tenant_id: int, ticker: str, event_date: date, window: str) -> str:
    import hashlib

    raw = f"{VERSION}:{tenant_id}:{ticker.upper()}:{event_date.isoformat()}:{window}"
    return hashlib.sha256(raw.encode()).hexdigest()[:160]


def _event_payload(event: dict[str, Any], window: str) -> dict[str, Any]:
    """Diccionario ``earnings`` del metadata de la alerta (lo lee la plantilla)."""
    return {
        "ticker": str(event["ticker"]),
        "company_name": event.get("company"),
        "origin": event.get("origin"),
        "event_date": str(event["date"]),
        "session": event.get("session"),
        "fiscal_label": event.get("fiscal_label"),
        "confirmed": event.get("confirmed"),
        "source": event.get("source"),
        "source_url": event.get("source_url"),
        "window": window,
        "rule_version": VERSION,
    }


def _market_today(company: Any, now: datetime) -> date:
    """"Hoy" en la zona del mercado de la linea real; UTC si no se puede asegurar."""
    tz_name = market_timezone(yahoo_symbol(company) or "") if company is not None else None
    if not tz_name:
        return now.date()
    return now.astimezone(ZoneInfo(tz_name)).date()


def due_reminders(db: Session, now: datetime) -> list[tuple[dict[str, Any], str, int | None]]:
    """(payload, ventana, company_id) de los avisos que tocan ahora. Sin red."""
    followed = followed_companies(db)
    if not followed:
        return []
    today = now.date()
    calendar = followed_calendar(db, today, today + timedelta(days=HORIZON_DAYS), now=now)
    due: list[tuple[dict[str, Any], str, int | None]] = []
    for day in calendar["days"]:
        for event in day["events"]:
            info = followed.get(str(event["ticker"]))
            company = info["company"] if info else None
            event_date = date.fromisoformat(str(event["date"]))
            days_until = (event_date - _market_today(company, now)).days
            window = next((w for w, d in WINDOW_DAYS.items() if d == days_until), None)
            if window is None:
                continue
            due.append((_event_payload(event, window), window, getattr(company, "id", None)))
    return due


def emit_earnings_reminders(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Persiste y despacha los avisos que toquen; idempotente por fecha y ventana."""
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise ValueError("Tenant context required")
    settings = get_settings()
    now = (now or datetime.now(UTC)).astimezone(UTC)
    summary: dict[str, Any] = {
        "enabled": bool(settings.earnings_alerts_enabled),
        "created": 0,
        "existing": 0,
        "alert_ids": [],
        "errors": [],
    }
    if not settings.earnings_alerts_enabled:
        return summary
    created: list[ResearchAlert] = []
    for payload, window, company_id in due_reminders(db, now):
        fingerprint = _fingerprint(tenant_id, payload["ticker"], date.fromisoformat(payload["event_date"]), window)
        if db.scalar(select(ResearchAlert.id).where(
                ResearchAlert.tenant_id == tenant_id,
                ResearchAlert.fingerprint == fingerprint)) is not None:
            summary["existing"] += 1
            continue
        alert = ResearchAlert(
            tenant_id=tenant_id,
            company_id=company_id,
            severity=SEVERITY_BY_WINDOW[window],
            status="open",
            alert_type=ALERT_TYPE,
            title=earnings_alert_copy.title(payload)[:300],
            message=earnings_alert_copy.message_text(payload),
            fingerprint=fingerprint,
            channels=alert_channels(settings),
            last_triggered_at=now,
            metadata_={"earnings": payload},
        )
        try:
            with db.begin_nested():
                db.add(alert)
                db.flush()
                # Intencion de entrega durable por canal externo, en la misma
                # transaccion (patron dca_signal_service._emit_alert_row).
                for channel in alert.channels or []:
                    if channel in ("in_app", "telegram"):
                        continue
                    db.add(AlertDelivery(tenant_id=tenant_id, alert_id=alert.id, channel=channel))
        except IntegrityError:
            summary["existing"] += 1
            continue
        created.append(alert)
    db.commit()
    from app.services.notification_service import NotificationService

    for alert in created:
        try:
            NotificationService().dispatch(db, alert)
        except Exception:  # noqa: BLE001 - el aviso queda en la app aunque falle un canal
            logger.warning("earnings dispatch failed alert_id=%s", alert.id, exc_info=True)
            db.rollback()
            summary["errors"].append(f"alert_id={alert.id}")
    summary["created"] = len(created)
    summary["alert_ids"] = [alert.id for alert in created]
    return summary
