"""Opt-in routing over the durable research-alert/outbox pipeline. No provider reads."""
from datetime import UTC, datetime

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.models import AlertDelivery, AlertSubscription, NewsEvent, PushPreference, ResearchAlert

ALERT_TYPE_MACRO = "macro_event"
EVENT_TYPES = ("thesis_broken", "new_filing", "insiders", "shorts_rising", "daily_digest", "dca_levels", "macro_event", "earnings")


def event_type(db: Session, alert: ResearchAlert) -> str | None:
    kind = alert.alert_type
    if kind == "daily_digest":
        return "daily_digest"
    if kind == "dca_level":
        return "dca_levels"
    if kind == ALERT_TYPE_MACRO:
        return "macro_event"
    if kind == "earnings_reminder":
        return "earnings"
    if kind in {"thesis_broken", "claim_contradicted"}:
        return "thesis_broken"
    if kind.startswith("insider_"):
        return "insiders"
    if kind in {"shorts_rising", "short_interest_buildup"}:
        return "shorts_rising"
    if kind in {"filing_changes", "earnings_release", "new_filing"}:
        return "new_filing"
    if kind == "tracked_news":
        news_id = (alert.metadata_ or {}).get("news_event_id")
        news = db.get(NewsEvent, news_id) if news_id else None
        # Provenance from the persisted source, never guess from a headline.
        if news and news.tenant_id == alert.tenant_id and (news.metadata_ or {}).get("connector") == "sec":
            return "new_filing"
    return None


def alert_category(db: Session, alert: ResearchAlert) -> str | None:
    """Tipo de evento de la alerta si es del tenant de la sesión; si no, ``None``.

    Las tres comprobaciones de cobertura (Telegram, push, correo) abrían con
    esta misma guarda copiada: sin tipo de evento, o con la alerta de otro
    tenant, la alerta no tiene canal.
    """
    category = event_type(db, alert)
    if not category or alert.tenant_id is None or alert.tenant_id != db.info.get("tenant_id"):
        return None
    return category


def alert_after_opt_in(created_at: datetime, enabled_at: datetime) -> bool:
    """``True`` si la alerta nació tras el alta de la preferencia/suscripción.

    Un aviso anterior al alta no se manda por un canal nuevo. Ambos lados se
    normalizan a tz-aware (UTC) antes de comparar.
    """
    created, since = created_at, enabled_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return created >= since


def subscription_for(db: Session, alert: ResearchAlert) -> AlertSubscription | None:
    category = alert_category(db, alert)
    if category is None:
        return None
    row = db.scalar(select(AlertSubscription).where(
        AlertSubscription.tenant_id == alert.tenant_id,
        AlertSubscription.event_type == category,
        AlertSubscription.enabled.is_(True),
    ))
    if not row or row.user_id != db.info.get("user_id"):
        return None
    from app.services.telegram_link import binding_for

    if not binding_for(db, alert.tenant_id, row.user_id, row.chat_id):
        return None
    return row if alert_after_opt_in(alert.created_at, row.enabled_at) else None


def dispatch_pending(db: Session, *, limit: int = 100) -> dict:
    """Periodic catch-up for emitters that only persist alerts, bounded/no replay."""
    from app.services.notification_service import NotificationService
    from app.services.web_push import preference_for

    tenant = db.info.get("tenant_id")
    if tenant is None or not db.info.get("user_id"):
        return {"candidates": 0, "redispatched": 0, "errors": []}
    types = list(db.scalars(select(AlertSubscription.event_type).where(
        AlertSubscription.tenant_id == tenant,
        AlertSubscription.user_id == db.info["user_id"],
        AlertSubscription.enabled.is_(True),
    )))
    push_types = list(db.scalars(select(PushPreference.event_type).where(
        PushPreference.tenant_id == tenant,
        PushPreference.user_id == db.info["user_id"],
        PushPreference.enabled.is_(True),
    )))
    types = list(dict.fromkeys([*types, *push_types]))
    if not types:
        return {"candidates": 0, "redispatched": 0, "errors": []}
    categories = []
    if "thesis_broken" in types:
        categories.append(ResearchAlert.alert_type.in_(("thesis_broken", "claim_contradicted")))
    if "insiders" in types:
        categories.append(ResearchAlert.alert_type.like("insider_%"))
    if "shorts_rising" in types:
        categories.append(ResearchAlert.alert_type.in_(("shorts_rising", "short_interest_buildup")))
    if "new_filing" in types:
        categories.append(ResearchAlert.alert_type.in_(("filing_changes", "earnings_release", "new_filing", "tracked_news")))
    if "daily_digest" in types:
        categories.append(ResearchAlert.alert_type == "daily_digest")
    if "dca_levels" in types:
        categories.append(ResearchAlert.alert_type == "dca_level")
    if "macro_event" in types:
        categories.append(ResearchAlert.alert_type == ALERT_TYPE_MACRO)
    if "earnings" in types:
        categories.append(ResearchAlert.alert_type == "earnings_reminder")
    starts = [db.scalar(select(model.enabled_at).where(
        model.tenant_id == tenant, model.enabled.is_(True),
    ).order_by(model.enabled_at).limit(1)) for model in (AlertSubscription, PushPreference)]
    oldest = min((value for value in starts if value is not None), key=lambda v: v.replace(tzinfo=None))
    # Excluding delivered/pending outbox rows prevents the first page from
    # starving later events; ineligible records are filtered by category below.
    candidates = list(db.scalars(select(ResearchAlert).where(
        ResearchAlert.tenant_id == tenant,
        ResearchAlert.created_at >= oldest,
        ResearchAlert.status == "open",
        ~exists().where(AlertDelivery.alert_id == ResearchAlert.id,
                        AlertDelivery.channel.in_(("telegram", "push"))),
        or_(*categories),
    ).order_by(ResearchAlert.id).limit(limit)))
    stats = {"candidates": len(candidates), "redispatched": 0, "errors": []}
    for alert in candidates:
        if subscription_for(db, alert) is None and preference_for(db, alert) is None:
            # Record terminal skip without HTTP. Prevents a page of non-filing
            # news or events from before a later opt-in starving newer alerts.
            svc = NotificationService()
            svc._ensure_delivery_row(db, alert, "telegram")
            svc._finish_delivery(db, alert, "telegram", "skipped", "Sin consentimiento aplicable")
            continue
        try:
            alert.channels = list(dict.fromkeys([*alert.channels, "telegram"]))
            db.commit()
            NotificationService().dispatch(db, alert)
            stats["redispatched"] += 1
        except Exception:
            db.rollback()
            stats["errors"].append(f"alert_id={alert.id}")
    return stats
