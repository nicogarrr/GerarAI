"""Dated sourced article alerts for tenant-held and watched companies.

An article mentioning a company is not proof that its headline is true or that
it caused a price move. The alert is a pointer to a source for user review.
"""
from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import and_, desc, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.i18n import generation_language
from app.models import Company, NewsEvent, Position, ResearchAlert, WatchItem
from app.services.notification_service import NotificationService
from app.services.ticker_news_lane import _NAME_NOISE, VERIFIED_ALIASES

VERSION = "tracked-news-v1"
MAX_AGE = timedelta(hours=48)
COOLDOWN = timedelta(hours=6)
# Deterministic title-only gate, not the potentially LLM-augmented materiality
# score or an inferred causal claim. Multilingual terms include ITU spectrum
# filings as an area of interest, not as an assertion of official approval.
EVENT_TERMS = re.compile(
    r"\b(?:filing|filed|register(?:ed|s)?|registration|sec|fda|fcc|itu|spectrum|"
    r"earnings|guidance|results|merger|acquisition|contract|award|launch|"
    r"bankruptcy|default|offering|dilution|recall|investigation|approval|"
    r"presenta(?:do|ción)?|registro|espectro|resultados|contrato|"
    r"adquisición|fusión|quiebra|investigación|aprobación)\b",
    re.IGNORECASE,
)


def _valid_source_url(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url.strip())
        if parsed.scheme.lower() not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            return None
    except ValueError:
        return None
    return url.strip()


def _headline_cites(company: Company, headline: str) -> bool:
    ticker = (company.ticker or "").upper()
    terms = [ticker, *VERIFIED_ALIASES.get(ticker, ())]
    terms += [w for w in re.split(r"\W+", company.name or "") if len(w) >= 4 and w.lower() not in _NAME_NOISE]
    return any(re.search(rf"(?<![\w]){re.escape(t)}(?![\w])", headline, flags=re.IGNORECASE) for t in terms if t)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _copy(language: str, ticker: str, headline: str, source: str, day: str, gdelt: bool) -> tuple[str, str]:
    """(titulo, mensaje) del aviso en el idioma guardado del usuario; espanol por defecto."""
    if language == "en":
        date_phrase = f"detected by GDELT on {day}" if gdelt else f"dated {day} by {source}"
        return (f"News about {ticker}: {headline}"[:300],
                f"Article from {source}, {date_phrase}: {headline}. "
                "Check the source; the GDELT date is not the publication date "
                "and the headline alone does not confirm the facts.")
    date_phrase = f"detectada por GDELT el {day}" if gdelt else f"fechada el {day} por {source}"
    return (f"Noticia sobre {ticker}: {headline}"[:300],
            f"Artículo de {source}, {date_phrase}: {headline}. "
            "Revisa la fuente; la fecha de GDELT no es la fecha de publicación "
            "y el titular no confirma por sí solo los hechos.")


def _fingerprint(tenant_id: int, company_id: int, url: str) -> str:
    # Avoid mutable NewsEvent ID as dedup key: same URL can be re-ingested.
    return hashlib.sha256(f"{VERSION}|{tenant_id}|{company_id}|{url}".encode()).hexdigest()


def evaluate(db: Session, *, now: datetime | None = None, limit: int = 500) -> dict:
    """Only article links with reliable publication dates; tenant-isolated idempotent outbox."""
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise ValueError("Tenant context required")
    # Idioma guardado del usuario (Ajustes); sin preferencia, espanol como siempre.
    language = generation_language(db)
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware now required")
    held = set(
        db.scalars(
            select(Position.company_id).where(
                Position.quantity > 0,
                Position.tenant_id == tenant_id,
            )
        ).all()
    )
    symbols = {
        symbol.upper()
        for symbol in db.scalars(
            select(WatchItem.symbol).where(WatchItem.tenant_id == tenant_id)
        ).all()
        if symbol
    }
    watched = set(db.scalars(select(Company.id).where(Company.ticker.in_(symbols))).all()) if symbols else set()
    tracked = held | watched
    stats = {"eligible_companies": len(tracked), "examined": 0, "created": 0,
             "duplicates": 0, "cooldown_skips": 0, "unverified_skips": 0}
    if not tracked:
        return stats
    since = now - MAX_AGE
    # SQL filters cheap provenance before each bounded page. Keyset scans
    # across pages, so 500 old ineligible rows cannot starve new filings.
    # Preserve date ordering for per-ticker cooldown decisions.
    eligible = and_(
        NewsEvent.tenant_id == tenant_id,
        NewsEvent.company_id.in_(tracked),
        NewsEvent.date >= since,
        NewsEvent.date <= now,
        NewsEvent.url.is_not(None),
        NewsEvent.metadata_["connector"].as_string().in_(("gdelt", "rss", "ir", "sec")),
        NewsEvent.metadata_["date_source"].as_string().in_(("source", "gdelt_first_seen")),
        NewsEvent.metadata_["source_headline"].as_string().is_not(None),
    )
    companies = {c.id: c for c in db.scalars(select(Company).where(Company.id.in_(tracked))).all()}
    cursor = None
    while True:
        query = select(NewsEvent).where(eligible)
        if cursor is not None:
            query = query.where(tuple_(NewsEvent.date, NewsEvent.id) > cursor)
        candidates = db.scalars(query.order_by(NewsEvent.date, NewsEvent.id).limit(limit)).all()
        if not candidates:
            break
        for event in candidates:
            stats["examined"] += 1
            url = _valid_source_url(event.url)
            published = _aware(event.date)
            # GDELT `seendate` is first-seen, not the publisher's publication
            # date. Both are usable recency evidence, but NEVER conflate them.
            provenance = event.metadata_ or {}
            date_source = provenance.get("date_source")
            # Old GDELT rows say `source` even though seendate is first-seen,
            # not publication. The fallback marker remains ineligible.
            if provenance.get("connector") == "gdelt" and date_source == "source":
                date_source = "gdelt_first_seen"
            # Only trusted ingestion connectors, not arbitrary manual inputs.
            if (not url or not (event.source or "").strip() or
                    provenance.get("connector") not in {"gdelt", "rss", "ir", "sec"} or
                    date_source not in {"source", "gdelt_first_seen"} or
                    published < since or published > now or not isinstance(provenance.get("source_headline"), str) or
                    not EVENT_TERMS.search(provenance["source_headline"])):
                stats["unverified_skips"] += 1
                continue
            company = companies.get(event.company_id)
            if company is None:
                continue
            # Noticias ya ingestadas ligadas al ticker del feed sin citar a la empresa
            # (p. ej. un titular de Novo bajo NVDA): no generan alerta.
            if not _headline_cites(company, provenance["source_headline"]):
                stats["unverified_skips"] += 1
                continue
            fp = _fingerprint(tenant_id, company.id, url)
            prior_alert = db.scalar(select(ResearchAlert).where(
                ResearchAlert.tenant_id == tenant_id, ResearchAlert.fingerprint == fp,
            ))
            if prior_alert is not None:
                # A past queue_analysis commit may have failed after alert commit.
                # Repair on the next gated evaluation, without redispatching it.
                from app.services.alert_analysis_service import queue_analysis

                try:
                    queue_analysis(db, prior_alert)
                except Exception:
                    db.rollback()
                stats["duplicates"] += 1
                continue
            from app.services.news_identity import equivalent_news_alert

            if equivalent_news_alert(db, company_id=company.id, url=url, title=event.title, now=now) is not None:
                # La misma noticia ya avisó por otra vía (revisión de tesis o regla news).
                stats["duplicates"] += 1
                continue
            recent = db.scalar(select(ResearchAlert).where(
                ResearchAlert.tenant_id == tenant_id,
                ResearchAlert.company_id == company.id,
                ResearchAlert.alert_type == "tracked_news",
            ).order_by(desc(ResearchAlert.last_triggered_at)).limit(1))
            if recent is not None:
                last_triggered = _aware(recent.last_triggered_at or recent.created_at)
                # Cooldown-suppressed backlog cannot burst out six hours later.
                # A later alert only covers articles published after the last
                # notification, never previously skipped articles from that batch.
                if last_triggered > now - COOLDOWN or published <= last_triggered:
                    stats["cooldown_skips"] += 1
                    continue
            membership = [kind for kind, match in (("cartera", company.id in held), ("watchlist", company.id in watched)) if match]
            headline = provenance["source_headline"].strip()
            source_label = "detectada por GDELT" if date_source == "gdelt_first_seen" else "fechada por la fuente"
            title, message = _copy(language, company.ticker, headline, str(event.source),
                                   published.date().isoformat(), date_source == "gdelt_first_seen")
            alert = ResearchAlert(
                tenant_id=tenant_id, company_id=company.id, severity="medium", status="open",
                alert_type="tracked_news", title=title,
                message=message,
                fingerprint=fp, channels=["in_app"], last_triggered_at=now,
                metadata_={"news_event_id": event.id, "source_url": url, "source": event.source,
                           "published_at": published.isoformat(), "matching": membership,
                           "rule_version": VERSION, "date_source": date_source,
                           "date_label": source_label, "source_headline": headline,
                           **({"language": language} if language != "es" else {})},
            )
            try:
                # Savepoint protects the tenant-scoped unique fingerprint in a
                # concurrent run; never redeliver an existing alert.
                with db.begin_nested():
                    db.add(alert)
                    db.flush()
            except IntegrityError:
                stats["duplicates"] += 1
                continue
            db.commit()
            # Persist baseline work before enqueue: a Redis failure must not
            # erase a valid alert. Only a newly gated alert gets one analysis.
            from app.services.alert_analysis_service import queue_analysis

            try:
                queue_analysis(db, alert)
            except Exception:  # background work cannot erase valid alert
                db.rollback()
            NotificationService().dispatch(db, alert)
            stats["created"] += 1
        cursor = (candidates[-1].date, candidates[-1].id)
    return stats
