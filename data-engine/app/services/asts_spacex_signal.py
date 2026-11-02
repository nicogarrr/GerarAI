"""Senal de vigilancia ASTS: SpaceX/Starlink cierra acuerdo con una operadora.

Regla deterministica sobre titulares ya persistidos y citados: sin LLM, sin
cifras y sin inventar enlaces. Un titular no confirma por si solo los hechos:
la alerta es un puntero a la fuente para revision del usuario. Si SpaceX cierra
acuerdos con operadoras grandes, el argumento de que el foso de AST son sus
acuerdos con operadoras se debilita.
"""
from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.i18n import generation_language
from app.core.tenancy import tenant_filters
from app.models import Company, NewsEvent, Position, ResearchAlert, WatchItem
from app.services.notification_service import record_in_app_delivery
from app.services.tracked_news_alerts import _valid_source_url

VERSION = "asts-spacex-mno-v1"
ALERT_TYPE = "asts_spacex_mno_signal"
MAX_AGE = timedelta(hours=72)
# Listas cerradas. Un termino fuera de ellas no dispara nada.
_SPACEX = r"(?:spacex|starlink(?:\s+mobile)?)"
_MNOS = (
    r"(?:at&t|verizon|t-mobile|tmobile|vodafone|orange\s+(?:sa|france)|telef[oó]nica|movistar|"
    r"deutsche\s+telekom|telstra|optus|rogers|bell\s+canada|rakuten|kddi|ntt|softbank|"
    r"airtel|reliance\s+jio|am[eé]rica\s+m[oó]vil|telcel|telenor|swisscom|"
    r"liberty\s+global|echostar|bouygues|iliad|telecom\s+italia|tim\s+brasil|telus)"
)
# Patron conservador: actor, verbo de cierre, sustantivo de acuerdo y operadora
# como CONTRAPARTE ("with"/"con"). Sin proximidad libre: un sustantivo suelto
# (agreement/deal) no es un verbo y una operadora citada de pasada no es parte.
_SIGN = (
    r"(?:sign(?:s|ed)?|strik(?:es|e)|struck|reach(?:es|ed)?|seal(?:s|ed)?|ink(?:s|ed)?|"
    r"clinch(?:es|ed)?|secur(?:es|ed)|firma(?:n)?|firm[oó]|alcanza(?:n)?|cierra(?:n)?|cerr[oó])"
)
_NOUN = r"(?:agreement|deal|partnership|contract|acuerdo|alianza|contrato)"
_MOD = r"(?:an?|the|new|multi-year|multiyear|long-term|landmark|un|una|nuevo|nueva)"
_DEALP = rf"{_SIGN}\s+(?:{_MOD}\s+){{0,3}}{_NOUN}"
_MNO_B = rf"(?<![\w]){_MNOS}(?![\w])"
_SPX_B = rf"\b{_SPACEX}\b"
_PARTNER = r"(?:partners|teams\s+up|joins\s+forces)\s+with"
_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # SpaceX signs (a) deal with Verizon
        rf"{_SPX_B}\s+{_DEALP}\s+(?:with|con)\s+{_MNO_B}",
        # SpaceX partners with Verizon
        rf"{_SPX_B}\s+{_PARTNER}\s+{_MNO_B}",
        # SpaceX and Verizon reached an agreement
        rf"{_SPX_B}\s+(?:and|&|y)\s+{_MNO_B}\s+{_DEALP}",
        # Verizon signs deal with Starlink / Verizon partners with Starlink
        rf"{_MNO_B}\s+(?:{_DEALP}\s+(?:with|con)|{_PARTNER})\s+{_SPX_B}",
    )
)
# Negaciones, cancelaciones, suspensiones, planes o rumores: no son un acuerdo cerrado.
_RE_NOT_CLOSED = re.compile(
    r"\b(?:den(?:y|ies|ied)|no|not|never|cancel(?:s|led|ed|ls)?|terminat\w*|collaps\w*|"
    r"scrap\w*|suspend\w*|halt\w*|paus\w*|abandon\w*|shelv\w*|axed?|withdr\w+|ditch\w*|unwind\w*|"
    r"walks?\s+away|breaks?|"
    r"talks?|negotiat\w*|plans?|planning|could|may|might|would|will|shall|should|reportedly|rumou?rs?|"
    r"if|whether|unless|when|once|expect(?:s|ed|ing)?|anticipat\w*|forecast\w*|predict\w*|"
    r"likely|unlikely|soon|poised|set\s+to|about\s+to|close\s+to|nears?|hopes?|bets?|speculat\w*|"
    r"analysts?|sources?\s+say|seg[uú]n|si|cuando|esperan?|espera(?:do|da)?|previsible|posible|"
    r"probable|pronostic\w*|"
    r"seeks?|eyes?|considers?|considering|fails?|failed|rejects?|rejected|drops?|dropped|ends?|ended|"
    r"niega|negó|cancela|cancelad[oa]|suspende|rechaza|conversaciones|negocia\w*|planea|podr[ií]a|rumor\w*|"
    r"sin acuerdo)\b",
    re.IGNORECASE,
)
# Acuerdos de la propia AST: no son la senal (es el argumento que se vigila).
_RE_AST = re.compile(r"\b(?:ast\s+spacemobile|ast\s+space\s+mobile|asts|ast)\b", re.IGNORECASE)


def matches(headline: str | None) -> bool:
    """Acuerdo cerrado entre SpaceX/Starlink y una operadora de la lista, con la
    operadora como contraparte; sin negaciones/suspensiones/planes ni AST."""
    if not headline or not isinstance(headline, str):
        return False
    # Una pregunta no afirma nada: cualquier signo de interrogacion descarta.
    if "?" in headline or "¿" in headline:
        return False
    if _RE_AST.search(headline) or _RE_NOT_CLOSED.search(headline):
        return False
    return any(pattern.search(headline) for pattern in _PATTERNS)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _date_label(language: str, gdelt: bool) -> str:
    if language == "en":
        return "detected by GDELT" if gdelt else "dated by the source"
    return "detectada por GDELT" if gdelt else "fechada por la fuente"


def _copy(language: str, headline: str, source: str, day: str, gdelt: bool) -> tuple[str, str]:
    """Titulo y mensaje del aviso en el idioma guardado; el titular de la fuente no se traduce."""
    if language == "en":
        date_phrase = f"detected by GDELT on {day}" if gdelt else f"dated {day} by the source"
        return (f"ASTS signal: {headline}"[:300],
                f"Article from {source}, {date_phrase}: {headline}. "
                "Watch signal: if SpaceX closes deals with large carriers, the argument that AST's moat is its "
                "carrier agreements weakens. Check the source; the headline alone does not confirm the facts.")
    date_phrase = f"detectado por GDELT el {day}" if gdelt else f"fechado el {day} por la fuente"
    return (f"Señal ASTS: {headline}"[:300],
            f"Artículo de {source}, {date_phrase}: {headline}. "
            "Señal de vigilancia: si SpaceX cierra acuerdos con operadoras grandes, "
            "el argumento de que el foso de AST son sus acuerdos con operadoras se debilita. "
            "Revisa la fuente; el titular no confirma por sí solo los hechos.")


def evaluate(db: Session, *, now: datetime | None = None) -> dict:
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise ValueError("Tenant context required")
    now = now or datetime.now(UTC)
    stats = {"examined": 0, "created": 0, "duplicates": 0, "skipped": 0}
    asts = db.scalar(select(Company).where(Company.ticker == "ASTS"))
    if asts is None:
        return stats
    held = db.scalar(
        select(Position.id)
        .where(
            Position.company_id == asts.id,
            Position.quantity > 0,
            *tenant_filters(db, Position),
        )
        .limit(1)
    )
    watched = db.scalar(
        select(WatchItem.id)
        .where(
            WatchItem.symbol == "ASTS",
            *tenant_filters(db, WatchItem),
        )
        .limit(1)
    )
    if held is None and watched is None:
        return stats
    spcx = db.scalar(select(Company).where(Company.ticker == "SPCX"))
    company_ids = [asts.id] + ([spcx.id] if spcx else [])
    since = now - MAX_AGE
    rows = db.scalars(select(NewsEvent).where(
        NewsEvent.tenant_id == tenant_id, NewsEvent.company_id.in_(company_ids),
        NewsEvent.date >= since, NewsEvent.date <= now, NewsEvent.url.is_not(None),
    ).order_by(desc(NewsEvent.date)).limit(500)).all()
    for event in rows:
        stats["examined"] += 1
        meta = event.metadata_ or {}
        # Solo el titular textual del conector: sin fallback a event.title
        # (puede ser un resumen del pipeline no verificable).
        headline = meta.get("source_headline")
        url = _valid_source_url(event.url)
        # Misma procedencia que tracked_news: solo conectores de confianza y
        # fecha de la fuente o primera deteccion de GDELT.
        date_source = meta.get("date_source")
        # Filas GDELT antiguas dicen `source` aunque seendate es primera
        # deteccion, no publicacion: no se mezclan (igual que tracked_news).
        if meta.get("connector") == "gdelt" and date_source == "source":
            date_source = "gdelt_first_seen"
        if (not url or not (event.source or "").strip()
                or meta.get("connector") not in {"gdelt", "rss", "ir", "sec"}
                or date_source not in {"source", "gdelt_first_seen"}
                or not isinstance(headline, str) or not matches(headline)):
            stats["skipped"] += 1
            continue
        fp = hashlib.sha256(f"{VERSION}|{tenant_id}|{url}".encode()).hexdigest()
        if db.scalar(select(ResearchAlert.id).where(
                ResearchAlert.tenant_id == tenant_id, ResearchAlert.fingerprint == fp)) is not None:
            stats["duplicates"] += 1
            continue
        published = _aware(event.date)
        headline = headline.strip()
        # Idioma guardado del usuario (Ajustes); sin preferencia, espanol como siempre.
        language = generation_language(db)
        title, message = _copy(language, headline, str(event.source), published.date().isoformat(),
                               date_source == "gdelt_first_seen")
        alert = ResearchAlert(
            tenant_id=tenant_id, company_id=asts.id, severity="high", status="open",
            alert_type=ALERT_TYPE, title=title, message=message,
            fingerprint=fp, channels=["in_app"], last_triggered_at=now,
            metadata_={"news_event_id": event.id, "source_url": url, "source": event.source,
                       "published_at": published.isoformat(), "rule_version": VERSION,
                       "date_label": _date_label(language, date_source == "gdelt_first_seen"),
                       "date_source": date_source, "source_headline": headline,
                       **({"language": language} if language != "es" else {})},
        )
        try:
            with db.begin_nested():
                db.add(alert)
                db.flush()
                record_in_app_delivery(db, alert)
        except IntegrityError:
            stats["duplicates"] += 1
            continue
        db.commit()
        stats["created"] += 1
    return stats
