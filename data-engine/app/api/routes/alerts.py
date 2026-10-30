import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.ui_errors import ui_error
from app.models import AlertDelivery, AlertRule, Company, NewsEvent, ResearchAlert
from app.models.entities import InsiderFiling, InsiderTransaction
from app.schemas import (
    AlertRuleOut,
    ResearchAlertAction,
    ResearchAlertChannels,
    ResearchAlertOut,
)
from app.services.alert_rule_service import AlertRuleService
from app.services.company_resolver import resolve_company
from app.services.notification_service import NotificationService
from app.services.review_alert_service import ReviewAlertService

router = APIRouter()


class ManualAlertCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    alert_type: Literal["price_above", "price_below", "price_change", "news", "earnings"]
    operator: Literal[">", "<", ">=", "<=", "=="]
    value: float | str

    @field_validator("value")
    @classmethod
    def _finite_value(cls, value: float | str) -> float | str:
        from app.services.alert_rule_service import _is_non_finite

        if _is_non_finite(value):
            raise ValueError("value must be a finite number")
        return value

    @model_validator(mode="after")
    def _numeric_threshold(self) -> "ManualAlertCreate":
        # Las alertas de precio y de cambio comparan números: un umbral de texto
        # («abc», «1,234») se guardaba igual y la regla no podía dispararse nunca,
        # sin ningún aviso (``_matches`` solo admite == / != sobre texto).
        from app.services.alert_rule_service import _numeric_threshold

        if self.alert_type in {"price_above", "price_below", "price_change"}:
            if _numeric_threshold(self.value) is None:
                raise ValueError("El umbral de una alerta de precio o de cambio debe ser un número")
        return self


def _is_unverified_stub(company: Company) -> bool:
    """Ficha creada solo con el ticker y nunca enriquecida (nombre = ticker, bolsa desconocida)."""
    return (
        (company.name or "").strip().upper() == (company.ticker or "").strip().upper()
        and (company.exchange or "UNKNOWN").strip().upper() == "UNKNOWN"
        and company.company_type == "research_candidate"
    )


@router.post("", response_model=AlertRuleOut, status_code=201)
def create_alert(
    payload: ManualAlertCreate, db: Session = Depends(get_db)
) -> AlertRule:
    company = resolve_company(db, payload.ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if _is_unverified_stub(company):
        # /companies/ensure crea una ficha minima para cualquier ticker con formato valido;
        # si Finnhub no la reconocio (sigue sin nombre ni bolsa), no se crean alertas sobre ella.
        raise ui_error(422, "symbol_not_recognized", ticker=company.ticker)
    return AlertRuleService().create(
        db,
        company,
        rule_type=payload.alert_type,
        operator=payload.operator,
        value=payload.value,
    )


@router.get("/rules", response_model=list[AlertRuleOut])
def list_alert_rules(
    ticker: str | None = None,
    active: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> list[AlertRule]:
    statement = select(AlertRule)
    if ticker:
        company = resolve_company(db, ticker)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        statement = statement.where(AlertRule.company_id == company.id)
    if active is not None:
        statement = statement.where(AlertRule.active.is_(active))
    return list(
        # id como desempate: con created_at repetido (reglas creadas en lote) LIMIT/OFFSET
        # sin orden total repetia o saltaba reglas entre paginas en Postgres.
        db.scalars(
            statement.order_by(desc(AlertRule.created_at), desc(AlertRule.id)).limit(limit).offset(offset)
        ).all()
    )


@router.get("/telegram-status")
def telegram_status() -> dict:
    """Presencia de la configuracion Telegram para la guia de /alerts.

    Solo booleanos: ningun secreto (token, chat_id, URL) sale por la API.
    """
    settings = get_settings()
    enabled = bool(settings.telegram_enabled)
    has_token = bool(settings.telegram_bot_token)
    has_chat = bool(settings.telegram_chat_id)
    return {
        "enabled": enabled,
        "has_bot_token": has_token,
        "has_chat_id": has_chat,
        "configured": enabled and has_token and has_chat,
    }


@router.post("/rules/evaluate")
def evaluate_alert_rules(db: Session = Depends(get_db)) -> dict:
    results = AlertRuleService().evaluate_all(db)
    return {"status": "ok", "evaluated": len(results), "results": results}


@router.delete("/rules/{rule_id}", response_model=AlertRuleOut)
def deactivate_alert_rule(
    rule_id: int, db: Session = Depends(get_db)
) -> AlertRule:
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    rule.active = False
    db.commit()
    db.refresh(rule)
    return rule


def _snooze_expired(snoozed_until: datetime | None, now: datetime) -> bool:
    """¿Caducó el snooze?

    `snoozed_until` llega del cliente como `datetime` (Pydantic no le impone
    zona) y la base lo devuelve naive: SQLite no guarda el offset, asi que al
    releerlo se pierde el tz y `naive <= aware` lanza
    `TypeError: can't compare offset-naive and offset-aware datetimes`. Se
    normaliza a UTC asumiendo que un valor naive ya esta en UTC, que es como se
    escribe en el resto de la app.
    """
    if snoozed_until is None:
        return False
    value = (
        snoozed_until
        if snoozed_until.tzinfo is not None
        else snoozed_until.replace(tzinfo=UTC)
    )
    return value <= now


def _safe_http_url(value: object) -> str | None:
    """Solo una URL absoluta http/https con host puede salir como enlace: el
    valor acaba en el href de un <a target="_blank"> y NewsEvent.url acepta
    cualquier string, asi que javascript:/data:/relativas se descartan (None)
    en la frontera de salida en lugar de llegar al cliente."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = urlparse(value.strip())
        hostname = parsed.hostname
    except ValueError:
        # URL malformada («https://[broken/path»): una alerta asi no puede
        # tumbar el GET /api/alerts entero con un 500. El acceso a
        # .hostname tambien puede lanzar ValueError (corchetes IPv6 rotos).
        return None
    if parsed.scheme in ("http", "https") and hostname:
        return value.strip()
    return None


@router.get("", response_model=list[ResearchAlertOut])
def list_alerts(
    ticker: str | None = None,
    status: str | None = None,
    include_snoozed: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[ResearchAlertOut]:
    now = datetime.now(UTC)
    # Product feed is not an operations console. Filter BEFORE limit so an
    # operational alert cannot consume a user-visible slot. Keep stored rows.
    # Legacy TypeSafe incidents predate the explicit audience marker.
    statement = select(ResearchAlert).where(
        ResearchAlert.alert_type != "typesafe_credit_exhausted",
        or_(
            ResearchAlert.metadata_["audience"].as_string().is_(None),
            ResearchAlert.metadata_["audience"].as_string() != "internal_ops",
        ),
    )
    if ticker:
        # F313: mismo criterio de identidad que /api/alerts/rules (que sí
        # usa resolve_company): el alias europeo SAN.MC resuelve SAN; el
        # match literal devolvía 404 para la misma entidad.
        company = resolve_company(db, ticker)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        statement = statement.where(ResearchAlert.company_id == company.id)
    if status:
        statement = statement.where(ResearchAlert.status == status)
    elif not include_snoozed:
        # Solo REAPARECEN las alertas cuyo snooze ya caduco: un snooze sin
        # fecha es indefinido (silenciar = ocultar) y uno con fecha futura
        # sigue activo; ambos quedan fuera salvo include_snoozed=True.
        # (`snoozed_until <= now` con NULL evalua a NULL -> excluida, que es
        # exactamente la semantica de snooze indefinido.)
        statement = statement.where(
            or_(
                ResearchAlert.status != "snoozed",
                ResearchAlert.snoozed_until <= now,
            )
        )
    # «Ultimos disparos» se ordena por el ultimo disparo real: un re-disparo
    # reciente de una huella antigua debe salir primero. Filas antiguas sin
    # last_triggered_at caen al unico instante conocido (created_at).
    alerts = list(
        db.scalars(
            statement.order_by(
                desc(func.coalesce(ResearchAlert.last_triggered_at, ResearchAlert.created_at)),
                desc(ResearchAlert.id),
            ).limit(limit)
        ).all()
    )
    # Un GET no escribe. Antes el handler reabria las alertas cuyo snooze habia
    # caducado y hacia commit, lo que hacia la operacion no idempotente (dos
    # GET seguidos no dan el mismo resultado), rompia cualquier cache HTTP de la
    # ruta, y podia devolver 500 en un camino de lectura. Aqui solo se refleja
    # el estado derivado en la respuesta, sin tocar la fila: la fila queda
    # 'snoozed' en base y cada respuesta deriva a 'open' sin escritura.
    # El estado derivado se refleja en DTOs, NUNCA en las entidades ORM:
    # mutarlas dejaba la sesion sucia y cualquier commit posterior del mismo
    # request podia flushear una escritura desde un GET.
    company_ids = {alert.company_id for alert in alerts if alert.company_id is not None}
    companies = (
        {
            company.id: company
            for company in db.scalars(select(Company).where(Company.id.in_(company_ids)))
        }
        if company_ids
        else {}
    )
    # F172: la URL de la fuente viene de metadata.source_url (alertas insider)
    # o del NewsEvent enlazado (alertas de filings/noticias). Sin URL no se
    # inventa enlace: source_url queda None y la UI solo ofrece la ficha.
    news_ids = {
        alert.metadata_.get("news_event_id")
        for alert in alerts
        if alert.metadata_ and alert.metadata_.get("news_event_id")
    }
    news_events = (
        {event.id: event for event in db.scalars(select(NewsEvent).where(NewsEvent.id.in_(news_ids)))}
        if news_ids else {}
    )
    # Older insider alerts retain a transaction fingerprint even when the
    # issuer has no Company row. Read identity from that exact source row,
    # never from the alert title, and keep the tenant in the lookup key.
    fingerprints = {
        alert.metadata_.get("tx_fingerprint")
        for alert in alerts
        if alert.alert_type.startswith("insider_") and alert.metadata_
        and isinstance(alert.metadata_.get("tx_fingerprint"), str)
    }
    insider_issuers = {}
    if fingerprints:
        rows = db.execute(
            select(InsiderTransaction, InsiderFiling)
            .join(InsiderFiling, InsiderFiling.id == InsiderTransaction.filing_id)
            .where(InsiderTransaction.fingerprint.in_(fingerprints))
        ).all()
        insider_issuers = {
            (tx.tenant_id, tx.fingerprint): (tx.issuer_ticker, filing.issuer_name)
            for tx, filing in rows
            if tx.tenant_id == filing.tenant_id
        }
    # Delivery rows are authoritative; metadata is only a legacy mirror and
    # may be absent (in-app creators) or stale (retries/backfill).
    delivery_rows = db.scalars(select(AlertDelivery).where(
        AlertDelivery.alert_id.in_([alert.id for alert in alerts]),
    )).all() if alerts else []
    deliveries = {}
    for row in delivery_rows:
        deliveries.setdefault((row.tenant_id, row.alert_id), {})[row.channel] = {
            "status": row.status,
            "attempted_at": row.updated_at.isoformat() if row.updated_at else None,
            "error": row.last_error,
        }
    result: list[ResearchAlertOut] = []
    for alert in alerts:
        out = ResearchAlertOut.model_validate(alert)
        company = companies.get(alert.company_id)
        out.ticker = company.ticker if company else None
        out.company_name = company.name if company else None
        metadata = alert.metadata_ or {}
        actual = deliveries.get((alert.tenant_id, alert.id), {})
        out.metadata = {**metadata, "deliveries": {**(metadata.get("deliveries") or {}), **actual}}
        if company is None and alert.alert_type.startswith("insider_"):
            fingerprint = metadata.get("tx_fingerprint")
            issuer = (
                insider_issuers.get((alert.tenant_id, fingerprint))
                if isinstance(fingerprint, str) else None
            )
            if issuer is not None:
                out.ticker, out.company_name = issuer
            elif isinstance(metadata.get("issuer_ticker"), str):
                out.ticker = metadata["issuer_ticker"].strip() or None
        event = news_events.get(metadata.get("news_event_id"))
        out.source_url = _safe_http_url(metadata.get("source_url")) or (
            _safe_http_url(event.url) if event else None
        )
        if event and company and alert.alert_type in ("tracked_news", "news_material_update"):
            # Use the same legacy-identity gate as News. Feed ticker labels
            # are not evidence that Novo headlines describe NVIDIA.
            from app.api.routes.news import _is_off_topic

            if _is_off_topic(event, company):
                continue
        if event and alert.alert_type in ("tracked_news", "news_material_update", "news"):
            title = (event.title or "").strip()
            out.event_headline = title or None
        if event:
            # Document type only from a specific form token in the source
            # headline, never from an arbitrary model summary or SEC domain.
            headline = (event.metadata_ or {}).get("source_headline")
            if isinstance(headline, str):
                match = re.search(r"\b(10-K|10-Q|8-K|20-F|6-K)\b", headline, re.IGNORECASE)
                out.event_form = match.group(1).upper() if match else None
            source = (event.metadata_ or {}).get("date_source")
            if source in ("source", "gdelt_first_seen"):
                out.event_date = event.date
                out.event_date_source = source
        if alert.status == "snoozed" and _snooze_expired(alert.snoozed_until, now):
            out.status = "open"
            out.snoozed_until = None
        result.append(out)
    return result


@router.get("/{alert_id}/analysis")
def get_alert_analysis(alert_id: int, db: Session = Depends(get_db)) -> dict:
    from app.services.alert_analysis_service import read_analysis

    try:
        return read_analysis(db, alert_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{alert_id}/action", response_model=ResearchAlertOut)
def action_alert(
    alert_id: int,
    payload: ResearchAlertAction,
    db: Session = Depends(get_db),
) -> ResearchAlert:
    alert = db.get(ResearchAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    try:
        ReviewAlertService().transition_alert(
            alert,
            action=payload.action,
            actor=payload.actor,
            snoozed_until=payload.snoozed_until,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/{alert_id}/dispatch")
def dispatch_alert(
    alert_id: int, db: Session = Depends(get_db)
) -> dict:
    alert = db.get(ResearchAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {
        "alert_id": alert.id,
        "deliveries": NotificationService().dispatch(db, alert),
    }


@router.patch("/{alert_id}/channels", response_model=ResearchAlertOut)
def update_alert_channels(
    alert_id: int,
    payload: ResearchAlertChannels,
    db: Session = Depends(get_db),
) -> ResearchAlert:
    alert = db.get(ResearchAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.channels = list(dict.fromkeys(payload.channels))
    db.commit()
    db.refresh(alert)
    return alert


class TelegramSubscriptionIn(BaseModel):
    enabled: bool = False
    chat_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$", description="Chat privado previamente vinculado mediante prueba del bot y confirmación del propietario")


class TelegramSubscriptionOut(BaseModel):
    event_type: Literal["thesis_broken", "new_filing", "insiders", "shorts_rising", "daily_digest", "dca_levels", "macro_event", "earnings"]
    enabled: bool
    chat_id: str | None = None


@router.get("/telegram-subscriptions", response_model=list[TelegramSubscriptionOut])
def list_telegram_subscriptions(db: Session = Depends(get_db)) -> list[dict]:
    from app.models import AlertSubscription
    from app.services.outbound_alerts import EVENT_TYPES

    if not db.info.get("tenant_id") or not db.info.get("user_id"):
        raise ui_error(401, "verified_identity_required")
    rows = {row.event_type: row for row in db.scalars(select(AlertSubscription).where(
        AlertSubscription.user_id == db.info["user_id"],
        AlertSubscription.tenant_id == db.info["tenant_id"],
    ))}
    return [{"event_type": kind, "enabled": rows[kind].enabled if kind in rows else False,
             "chat_id": rows[kind].chat_id if kind in rows else None} for kind in EVENT_TYPES]


@router.put("/telegram-subscriptions/{event_type}", response_model=TelegramSubscriptionOut)
def set_telegram_subscription(
    event_type: Literal["thesis_broken", "new_filing", "insiders", "shorts_rising", "daily_digest", "dca_levels", "macro_event", "earnings"],
    payload: TelegramSubscriptionIn,
    db: Session = Depends(get_db),
) -> dict:
    from app.models import AlertSubscription

    tenant, user = db.info.get("tenant_id"), db.info.get("user_id")
    if not tenant or not user:
        raise ui_error(401, "verified_identity_required")
    from app.services.telegram_link import binding_for

    if payload.enabled and not binding_for(db, tenant, user, payload.chat_id):
        raise ui_error(403, "chat_link_required")
    row = db.scalar(select(AlertSubscription).where(
        AlertSubscription.tenant_id == tenant, AlertSubscription.event_type == event_type,
    ))
    if row and row.user_id != user:
        raise ui_error(403, "subscription_owner_only")
    now = datetime.now(UTC)
    if row is None:
        row = AlertSubscription(tenant_id=tenant, user_id=user, event_type=event_type,
                                chat_id=payload.chat_id, enabled=payload.enabled, enabled_at=now)
        db.add(row)
    else:
        if payload.enabled and (not row.enabled or row.chat_id != payload.chat_id):
            row.enabled_at = now
        row.enabled, row.chat_id = payload.enabled, payload.chat_id
    db.commit()
    return {"event_type": event_type, "enabled": row.enabled, "chat_id": row.chat_id}


# --- Web Push (PWA) -------------------------------------------------------

PushEventType = Literal["thesis_broken", "new_filing", "insiders", "shorts_rising", "daily_digest",
                        "dca_levels", "macro_event", "earnings"]


class PushConfigOut(BaseModel):
    enabled: bool
    public_key: str | None = None


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200, pattern=r"^[A-Za-z0-9_\-=]+$")
    auth: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_\-=]+$")


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1000)
    keys: PushKeys
    user_agent: str | None = Field(default=None, max_length=200)


class PushEndpointIn(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1000)


class PushPreferenceIn(BaseModel):
    enabled: bool = False


class PushPreferenceOut(BaseModel):
    event_type: PushEventType
    enabled: bool


class PushStatusOut(BaseModel):
    enabled: bool
    public_key: str | None = None
    devices: int
    preferences: list[PushPreferenceOut]


def _push_identity(db: Session) -> tuple[int, str]:
    tenant, user = db.info.get("tenant_id"), db.info.get("user_id")
    if not tenant or not user:
        raise ui_error(401, "verified_identity_required")
    return tenant, user


@router.get("/push/config", response_model=PushConfigOut)
def push_config() -> dict:
    from app.services.web_push import is_configured

    settings = get_settings()
    ready = is_configured(settings)
    return {"enabled": ready, "public_key": settings.vapid_public_key if ready else None}


@router.get("/push/status", response_model=PushStatusOut)
def push_status(db: Session = Depends(get_db)) -> dict:
    from app.models import PushPreference
    from app.services.outbound_alerts import EVENT_TYPES
    from app.services.web_push import devices_for, is_configured

    tenant, user = _push_identity(db)
    settings = get_settings()
    ready = is_configured(settings)
    rows = {row.event_type: row.enabled for row in db.scalars(select(PushPreference).where(
        PushPreference.tenant_id == tenant, PushPreference.user_id == user))}
    return {"enabled": ready, "public_key": settings.vapid_public_key if ready else None,
            "devices": len(devices_for(db, tenant, user)),
            "preferences": [{"event_type": kind, "enabled": rows.get(kind, False)} for kind in EVENT_TYPES]}


@router.post("/push/subscriptions", status_code=201)
def register_push_device(payload: PushSubscriptionIn, db: Session = Depends(get_db)) -> dict:
    from app.models import PushSubscription
    from app.services.web_push import endpoint_hash, endpoint_is_allowed, is_configured

    tenant, user = _push_identity(db)
    if not is_configured(get_settings()):
        raise ui_error(409, "push_not_configured")
    if not endpoint_is_allowed(payload.endpoint):
        raise ui_error(422, "push_endpoint_unsupported")
    digest = endpoint_hash(payload.endpoint)
    row = db.scalar(select(PushSubscription).where(
        PushSubscription.tenant_id == tenant, PushSubscription.endpoint_hash == digest))
    if row is not None and row.user_id != user:
        raise ui_error(403, "device_belongs_to_other")
    if row is None:
        db.add(PushSubscription(tenant_id=tenant, user_id=user, endpoint=payload.endpoint,
                                endpoint_hash=digest, p256dh=payload.keys.p256dh,
                                auth_secret=payload.keys.auth, user_agent=payload.user_agent))
    else:
        row.p256dh, row.auth_secret, row.user_agent = payload.keys.p256dh, payload.keys.auth, payload.user_agent
    db.commit()
    return {"registered": True}


@router.post("/push/subscriptions/remove")
def remove_push_device(payload: PushEndpointIn, db: Session = Depends(get_db)) -> dict:
    from app.models import PushSubscription
    from app.services.web_push import endpoint_hash

    tenant, user = _push_identity(db)
    row = db.scalar(select(PushSubscription).where(
        PushSubscription.tenant_id == tenant, PushSubscription.user_id == user,
        PushSubscription.endpoint_hash == endpoint_hash(payload.endpoint)))
    if row is not None:
        db.delete(row)
        db.commit()
    return {"removed": row is not None}


@router.put("/push/preferences/{event_type}", response_model=PushPreferenceOut)
def set_push_preference(event_type: PushEventType, payload: PushPreferenceIn,
                        db: Session = Depends(get_db)) -> dict:
    from app.models import PushPreference
    from app.services.web_push import devices_for, is_configured

    tenant, user = _push_identity(db)
    if payload.enabled:
        if not is_configured(get_settings()):
            raise ui_error(409, "push_not_configured")
        if not devices_for(db, tenant, user):
            raise ui_error(403, "enable_notifications_first")
    row = db.scalar(select(PushPreference).where(
        PushPreference.tenant_id == tenant, PushPreference.user_id == user,
        PushPreference.event_type == event_type))
    now = datetime.now(UTC)
    if row is None:
        row = PushPreference(tenant_id=tenant, user_id=user, event_type=event_type,
                             enabled=payload.enabled, enabled_at=now)
        db.add(row)
    else:
        if payload.enabled and not row.enabled:
            row.enabled_at = now
        row.enabled = payload.enabled
    db.commit()
    return {"event_type": event_type, "enabled": row.enabled}
