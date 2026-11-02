"""Identidad de una noticia para no avisar dos veces de lo mismo.

Una misma noticia llegaba por tres vias (revision de tesis `news_material_update`,
regla `news` y `tracked_news`) y a veces con dos filas en `news_events` (la URL
cambia en query/fragmento). La clave es la URL normalizada (esquema+host en
minusculas, sin query ni fragmento, sin barra final); sin URL valida, el titular
normalizado. Una alerta por noticia y empresa.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import NewsEvent, ResearchAlert

NEWS_ALERT_TYPES = ("tracked_news", "news_material_update", "news_potential_invalidation",
                    "news_material_positive", "news")
_DEDUPE_WINDOW = timedelta(days=7)
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def normalize_url(url: str | None) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    path = parts.path.rstrip("/")
    return f"{parts.hostname.lower()}{path}"


def normalize_headline(title: str | None) -> str | None:
    if not isinstance(title, str):
        return None
    key = _NON_WORD.sub(" ", title.casefold()).strip()
    return key or None


def news_key(url: str | None, title: str | None) -> str | None:
    """Clave de identidad: URL normalizada, o titular normalizado si no hay URL."""
    u = normalize_url(url)
    if u:
        return f"u:{u}"
    t = normalize_headline(title)
    return f"t:{t}" if t else None


def _keys_for_alert(db: Session, alert: ResearchAlert) -> set[str]:
    meta = alert.metadata_ or {}
    keys: set[str] = set()
    event = db.get(NewsEvent, meta["news_event_id"]) if meta.get("news_event_id") else None
    url = meta.get("source_url") or (event.url if event else None)
    title = (event.title if event else None) or meta.get("source_headline")
    for candidate in (news_key(url, None), news_key(None, title)):
        if candidate:
            keys.add(candidate)
    return keys


def equivalent_news_alert(
    db: Session, *, company_id: int | None, url: str | None, title: str | None,
    now: datetime | None = None,
) -> ResearchAlert | None:
    """Alerta de noticia reciente de la misma empresa que ya cubre esta noticia."""
    if company_id is None:
        return None
    wanted = {k for k in (news_key(url, None), news_key(None, title)) if k}
    if not wanted:
        return None
    since = (now or datetime.now(UTC)) - _DEDUPE_WINDOW
    rows = db.scalars(
        select(ResearchAlert).where(
            ResearchAlert.company_id == company_id,
            ResearchAlert.alert_type.in_(NEWS_ALERT_TYPES),
        ).order_by(ResearchAlert.id.desc()).limit(300)
    ).all()
    for alert in rows:
        created = alert.created_at
        if created is not None:
            created = created if created.tzinfo else created.replace(tzinfo=UTC)
            if created < since:
                continue
        if _keys_for_alert(db, alert) & wanted:
            return alert
    return None


def equivalent_news_event(db: Session, *, company_id: int | None, url: str | None, title: str | None) -> NewsEvent | None:
    """news_events de la misma empresa con la misma URL normalizada o el mismo titular normalizado."""
    wanted_url = normalize_url(url)
    if wanted_url:
        host_path = wanted_url
        # icontains + autoescape: en Postgres LIKE distingue mayúsculas (un host
        # guardado como «WWW.Site.com» no casaba) y el «%»/«_» de una URL
        # («%20») hacía de comodín; con limit(50) sin orden la noticia buena
        # podía quedarse fuera. La comparación exacta sigue siendo la de abajo.
        candidates = db.scalars(
            select(NewsEvent)
            .where(NewsEvent.url.icontains(host_path, autoescape=True))
            .order_by(NewsEvent.id.desc())
            .limit(50)
        ).all()
        for event in candidates:
            if normalize_url(event.url) == wanted_url:
                return event
    wanted_title = normalize_headline(title)
    if wanted_title and company_id is not None:
        recent = db.scalars(
            select(NewsEvent).where(NewsEvent.company_id == company_id)
            .order_by(NewsEvent.id.desc()).limit(300)
        ).all()
        for event in recent:
            if normalize_headline(event.title) == wanted_title:
                return event
    return None
