"""Web Push (PWA) sobre el outbox de alertas. Gratis: claves VAPID propias.

* Consentimiento: el usuario activa el permiso del navegador y, por separado,
  cada tipo de evento (``push_preferences``), igual que Telegram.
* Seguridad: el endpoint lo aporta el cliente y el servidor hace POST a el, asi
  que solo se aceptan https y los servicios de push de los navegadores
  (anti-SSRF). Los endpoints no se registran ni se exportan.
* Contenido: titulo y texto de la propia alerta, sin ids tecnicos.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PushPreference, PushSubscription, ResearchAlert

# Servicios de push de Chrome/Edge/Android, Firefox, Safari/iOS y Windows.
ALLOWED_HOST_SUFFIXES = (
    "fcm.googleapis.com",
    "push.services.mozilla.com",
    "push.apple.com",
    "notify.windows.com",
)
MAX_BODY_CHARS = 180
PUSH_TTL_SECONDS = 6 * 3600


def endpoint_is_allowed(endpoint: str) -> bool:
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password or not host:
        return False
    if parts.port not in (None, 443):
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in ALLOWED_HOST_SUFFIXES)


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()


def is_configured(settings) -> bool:
    return bool(settings.web_push_enabled and settings.vapid_public_key
                and settings.vapid_private_key and settings.vapid_subject)


def preference_for(db: Session, alert: ResearchAlert) -> PushPreference | None:
    """Preferencia de push que cubre esta alerta, o None. Mismas garantias que Telegram."""
    from app.services.outbound_alerts import event_type

    category = event_type(db, alert)
    if not category or alert.tenant_id is None or alert.tenant_id != db.info.get("tenant_id"):
        return None
    user = db.info.get("user_id")
    row = db.scalar(select(PushPreference).where(
        PushPreference.tenant_id == alert.tenant_id,
        PushPreference.user_id == user,
        PushPreference.event_type == category,
        PushPreference.enabled.is_(True),
    ))
    if row is None:
        return None
    created, since = alert.created_at, row.enabled_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return row if created >= since else None


def devices_for(db: Session, tenant_id: int, user_id: str) -> list[PushSubscription]:
    return list(db.scalars(select(PushSubscription).where(
        PushSubscription.tenant_id == tenant_id, PushSubscription.user_id == user_id,
    ).order_by(PushSubscription.id)))


def build_payload(alert: ResearchAlert) -> str:
    body = " ".join((alert.message or "").split())
    if len(body) > MAX_BODY_CHARS:
        body = body[: MAX_BODY_CHARS - 1].rstrip() + "…"
    return json.dumps({"title": (alert.title or "GerarAI")[:120], "body": body,
                       "url": "/alerts", "tag": f"alert-{alert.id}"}, ensure_ascii=False)


def _send(info: dict[str, Any], data: str, settings) -> None:
    from pywebpush import webpush

    webpush(subscription_info=info, data=data, vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject}, ttl=PUSH_TTL_SECONDS,
            timeout=settings.web_push_timeout_seconds)


def _classify(exc: Exception) -> tuple[str, int | None, bool]:
    """(estado del outbox, Retry-After, dispositivo caducado)."""
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    if code in (404, 410):
        return "failed", None, True
    if code == 429:
        raw = (getattr(response, "headers", None) or {}).get("Retry-After")
        try:
            return "throttled", min(int(raw), 3600), False
        except (TypeError, ValueError):
            return "throttled", 600, False
    if isinstance(code, int) and 400 <= code < 500:
        return "failed", None, False
    return "unknown", None, False


def send_to_user(db: Session, settings, alert: ResearchAlert) -> dict:
    """Envia la alerta a todos los dispositivos del usuario de la sesion.

    Devuelve ``{"status", "error", "retry_after"?}`` con los estados del outbox.
    Un dispositivo caducado (404/410) se elimina; nunca se persiste texto de
    excepciones (pueden llevar el endpoint).
    """
    tenant_id, user_id = alert.tenant_id, db.info.get("user_id")
    if not is_configured(settings):
        return {"status": "not_configured", "error": "Web Push requiere WEB_PUSH_ENABLED y claves VAPID"}
    devices = devices_for(db, tenant_id, user_id) if tenant_id is not None and user_id else []
    if not devices:
        return {"status": "skipped", "error": "Sin dispositivos con notificaciones activadas"}
    data = build_payload(alert)
    delivered = 0
    worst: tuple[str, int | None] | None = None
    order = {"failed": 0, "unknown": 1, "throttled": 2}
    for device in devices:
        info = {"endpoint": device.endpoint, "keys": {"p256dh": device.p256dh, "auth": device.auth_secret}}
        try:
            _send(info, data, settings)
            delivered += 1
        except Exception as exc:
            status, retry_after, expired = _classify(exc)
            if expired:
                db.delete(device)
            if worst is None or order[status] > order[worst[0]]:
                worst = (status, retry_after)
    db.commit()
    if delivered:
        return {"status": "delivered", "error": None}
    status, retry_after = worst or ("unknown", None)
    result: dict = {"status": status, "error": "WebPushError"}
    if retry_after is not None:
        result["retry_after"] = retry_after
    return result
