"""Identidad de una noticia para no avisar dos veces de lo mismo.

Una misma noticia llegaba por tres vias (revision de tesis `news_material_update`,
regla `news` y `tracked_news`) y a veces con dos filas en `news_events` (la URL
cambia en query/fragmento). La clave es la URL normalizada (esquema+host en
minusculas, sin query ni fragmento, sin barra final); sin URL valida, el titular
normalizado. Una alerta por noticia y empresa.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import String, func, literal, select, union_all
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


# Candidatos por URL que mira equivalent_news_event: los 50 más recientes cuyo
# url contiene «host/path» (sin distinguir mayúsculas).
_URL_CANDIDATES = 50
# Patrones por consulta en la lectura en lote (acota filas devueltas: ≤50 por patrón).
_BATCH_PATTERNS = 100
_BATCH_URLS = 500


def _like_autoescape(value: str) -> str:
    """El mismo escape que ``icontains(..., autoescape=True)`` (carácter «/»)."""
    return value.replace("/", "//").replace("%", "/%").replace("_", "/_")


@dataclass
class NewsDedupBatch:
    """Lecturas de deduplicación hechas UNA vez por tanda de un feed.

    Antes, cada noticia hacía ``url = $1`` (270 ms en producción) y
    ``lower(url) LIKE '%host/path%' ORDER BY id DESC LIMIT 50`` (un seq scan de
    toda la tabla, 3,1 s por noticia). Aquí se leen de golpe, para las filas
    con ``id <= max_id`` (lo que existía al empezar la tanda): las URL exactas
    ya guardadas y, por patrón, los 50 candidatos más recientes. Las filas
    nuevas (``id > max_id``, incluidas las que inserta la propia tanda) se
    siguen consultando por noticia, por rango de clave primaria (barato), así
    que el resultado es idéntico al de las consultas sueltas.
    """

    max_id: int
    known_urls: set[str] = field(default_factory=set)
    url_candidates: dict[str, list[tuple[int, str | None]]] = field(default_factory=dict)


def prefetch_news_dedup(
    db: Session,
    urls: Iterable[str | None],
    *,
    pattern_urls: Iterable[str | None] = (),
) -> NewsDedupBatch:
    """Precarga la deduplicación de una tanda.

    ``urls``: URL tal cual de las noticias (``_is_duplicate`` las busca exactas,
    con el filtro de tenant). ``pattern_urls``: URL de las noticias cuyo
    titular identifica el evento (las que llegan a ``equivalent_news_event``).
    """
    from app.core.tenancy import tenant_filters

    max_id = db.scalar(select(func.max(NewsEvent.id))) or 0
    batch = NewsDedupBatch(max_id=max_id)
    exact = sorted({u for u in urls if u})
    for start in range(0, len(exact), _BATCH_URLS):
        chunk = exact[start:start + _BATCH_URLS]
        batch.known_urls.update(
            u for u in db.scalars(
                select(NewsEvent.url).where(
                    NewsEvent.url.in_(chunk),
                    NewsEvent.id <= max_id,
                    *tenant_filters(db, NewsEvent),
                )
            ) if u
        )
    patterns = sorted({
        host_path
        for u in pattern_urls
        if u and u not in batch.known_urls and (host_path := normalize_url(u))
    })
    for start in range(0, len(patterns), _BATCH_PATTERNS):
        chunk = patterns[start:start + _BATCH_PATTERNS]
        # Tabla de patrones como UNION ALL de literales (VALUES con alias de
        # columnas no existe en SQLite).
        pats = union_all(*(
            select(
                literal(hp, String).label("host_path"),
                literal(_like_autoescape(hp), String).label("pattern"),
            )
            for hp in chunk
        )).subquery("dedup_patterns")
        rank = func.row_number().over(
            partition_by=pats.c.host_path, order_by=NewsEvent.id.desc()
        ).label("rank")
        # Misma condición que icontains(autoescape=True):
        # lower(url) LIKE '%' || lower(patrón) || '%' ESCAPE '/'.
        ranked = (
            select(pats.c.host_path, NewsEvent.id, NewsEvent.url, rank)
            .select_from(NewsEvent)
            .join(pats, func.lower(NewsEvent.url).like(
                "%" + func.lower(pats.c.pattern) + "%", escape="/"
            ))
            .where(NewsEvent.id <= max_id)
            .subquery()
        )
        for hp in chunk:
            batch.url_candidates[hp] = []
        rows = db.execute(
            select(ranked.c.host_path, ranked.c.id, ranked.c.url)
            .where(ranked.c.rank <= _URL_CANDIDATES)
            .order_by(ranked.c.host_path, ranked.c.id.desc())
        ).all()
        for hp, event_id, event_url in rows:
            batch.url_candidates[hp].append((event_id, event_url))
    return batch


def equivalent_news_event(
    db: Session, *, company_id: int | None, url: str | None, title: str | None,
    batch: NewsDedupBatch | None = None,
) -> NewsEvent | None:
    """news_events de la misma empresa con la misma URL normalizada o el mismo titular normalizado."""
    wanted_url = normalize_url(url)
    if wanted_url:
        host_path = wanted_url
        prefetched = batch.url_candidates.get(host_path) if batch is not None else None
        if batch is not None and prefetched is not None:
            # Top-50 por id desc = filas nuevas de la tanda (id > max_id) y
            # después las precargadas, en ese orden.
            fresh = db.execute(
                select(NewsEvent.id, NewsEvent.url)
                .where(
                    NewsEvent.id > batch.max_id,
                    NewsEvent.url.icontains(host_path, autoescape=True),
                )
                .order_by(NewsEvent.id.desc())
                .limit(_URL_CANDIDATES)
            ).all()
            ranked = [(row[0], row[1]) for row in fresh] + prefetched
            for event_id, event_url in ranked[:_URL_CANDIDATES]:
                if normalize_url(event_url) == wanted_url:
                    found = db.get(NewsEvent, event_id)
                    if found is not None:
                        return found
        else:
            # icontains + autoescape: en Postgres LIKE distingue mayúsculas (un host
            # guardado como «WWW.Site.com» no casaba) y el «%»/«_» de una URL
            # («%20») hacía de comodín; con limit(50) sin orden la noticia buena
            # podía quedarse fuera. La comparación exacta sigue siendo la de abajo.
            candidates = db.scalars(
                select(NewsEvent)
                .where(NewsEvent.url.icontains(host_path, autoescape=True))
                .order_by(NewsEvent.id.desc())
                .limit(_URL_CANDIDATES)
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
