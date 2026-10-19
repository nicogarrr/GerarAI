"""Local regex extraction only: no embeddings, remote retrieval or LLM calls.

Independent means distinct known author/publisher, not distinct chunks or URLs.
Unknown origins never contribute to n_sources. Exact copies and shared source
URLs are connected before counting publishers, including across storage lanes.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BottleneckSignal,
    Document,
    DocumentChunk,
    KnowledgeChunk,
    KnowledgeDocument,
    NewsEvent,
)

# Intentionally conservative vocabulary. No free-form inferred sector labels.
THEMES = {
    "Semiconductores": r"\b(?:semiconductors?|chips?|gpus?|hbm|semiconductores|obleas|wafers?)\b",
    "Energía": r"\b(?:oil|gas|energy|electricity|power grid|petroleo|energia|electricidad|red electrica)\b",
    "Minerales": r"\b(?:copper|lithium|rare earths?|minerals?|cobre|litio|tierras raras|minerales)\b",
    "Transporte": r"\b(?:shipping|freight|ports?|logistics|transporte|fletes|puertos?|logistica)\b",
    "Centros de datos": r"\b(?:data cent(?:er|re)s?|centros? de datos)\b",
    "Industria aeroespacial": r"\b(?:satellites?|launches?|aerospace|aircraft|satelites?|lanzamientos?|aeroespacial|aviones)\b",
}
# Umbral de "detectado": fuentes (autores/editores) independientes necesarias.
# Unico dueno del numero: la ruta GET /bottlenecks, el descubrimiento y la
# etiqueta de la UI leen esta constante (Tester 6: un "2 de N" hardcodeado
# mentiria en cuanto el umbral cambiara).
MIN_SOURCES = 2

CONSTRAINT = re.compile(
    r"\b(?:shortages?|scarcity|supply constraints?|capacity constraints?|capacity bottlenecks?|"
    r"capacity shortages?|capacity constrained|limited capacity|insufficient capacity|capacity at (?:its )?limit|"
    r"backlogs?|escasez|restriccion(?:es)? de oferta|capacidad (?:limitada|insuficiente|saturada)|"
    r"cuellos? de botella|cartera de pedidos|pedidos pendientes)\b|"
    r"\b(?:lead times?|delivery times?|plazos? de entrega)\b.{0,45}\b"
    r"(?:longer|extended|lengthen\w*|increas\w*|weeks?|months?|largo\w*|aument\w*|semanas?|meses?)\b|"
    r"\b(?:longer|extended|long|largos?)\s+(?:lead times?|delivery times?|plazos? de entrega)\b"
)
# Falla cerrada: una mencion de escasez solo cuenta si NO hay negacion, alivio
# ni hipotesis en la misma frase. Perder una frase dudosa es preferible a abrir
# el estado "detectado" con ausencia de restriccion o con un escenario.
_NEG_WORDS = (
    r"no|not|never|without|nor|none|neither|n't|cannot|"
    r"sin|nunca|tampoco|ni|ningun[ao]?|jamas"
)
# Negacion ANTES de la escasez ("no chip shortages") hasta 6 palabras.
NEGATION = re.compile(rf"\b(?:{_NEG_WORDS})\b(?:\W+\w+){{0,6}}\W*$")
# Alivio ANTES ("resolved shortage", "end of the shortage").
RELIEF_BEFORE = re.compile(
    r"\b(?:easing|eased|resolved|eliminated|falling|shrinking|reduced|reduction in|end of|"
    r"overcome|alleviated|mitigated|cleared|resuelta|resuelto|fin de|superada|superado|"
    r"disminucion de|reduccion de|alivio de)\b(?:\W+\w+){0,3}\W*$"
)
# Negacion o alivio DESPUES ("shortages are not expected", "did not materialize",
# "shortage already resolved", "ya resuelta"), con cualquier adverbio intermedio.
AFTER_CUES = re.compile(
    rf"\b(?:{_NEG_WORDS}|easing|eased|easy|easier|resolved|ended|over|behind us|subsided|"
    r"alleviated|mitigated|cleared|disappeared|vanished|normali[sz]ed|overcome|unlikely|"
    r"improving|improved|falling|fell|shrinking|resuelt[ao]s?|superad[ao]s?|terminad[ao]s?|"
    r"disminuy\w+|reducid[ao]s?|mejor\w+|normalizad[ao]s?|improbable|descartad[ao]s?)\b"
)
# Hipotesis, escenario o riesgo: no es evidencia de una restriccion real.
CONDITIONAL = re.compile(
    r"\b(?:if|unless|whether|should|could|would|may|might|in case|in the event|"
    r"what if|scenario|hypothetical|potential|possible|possibly|risk of|risks of|fear|fears|"
    r"feared|worry|worried|concern(?:s|ed)? (?:about|over|of)|"
    r"si|salvo que|a menos que|en caso de|podria|podrian|podria ser|escenario|"
    r"hipotetic\w+|potencial|posible|posibles|riesgo de|riesgos de|temor|temores|preocupa\w*)\b"
)


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def extract_themes(text: str) -> set[str]:
    found: set[str] = set()
    for sentence in re.split(r"[.!?;\n]+", fold(text)):
        if CONDITIONAL.search(sentence):
            continue
        for match in CONSTRAINT.finditer(sentence):
            before = sentence[max(0, match.start() - 80):match.start()]
            after = sentence[match.end():match.end() + 80]
            if NEGATION.search(before) or RELIEF_BEFORE.search(before) or AFTER_CUES.search(after):
                continue
            # Co-occurrence within 100 characters, never across sentences.
            local = sentence[max(0, match.start() - 100):match.end() + 100]
            found.update(theme for theme, pattern in THEMES.items() if re.search(pattern, local))
    return found


@dataclass(frozen=True)
class Evidence:
    id: str
    text: str
    date: datetime
    origin: str | None
    identities: tuple[str, ...]


def _url_identity(url: str | None) -> tuple[str | None, str | None]:
    parsed = urlsplit(url or "")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host or parsed.scheme not in {"http", "https"}:
        return None, None
    # Query parameters / fragments do not create independent articles.
    # Group subdomains of the same publisher conservatively. Compound public
    # suffixes below cover common ingestion origins; no network PSL lookup.
    parts = host.split(".")
    compound_suffixes = {"co.uk", "com.au", "co.jp", "com.br", "co.in", "com.cn"}
    count = 3 if ".".join(parts[-2:]) in compound_suffixes else 2
    publisher = ".".join(parts[-count:])
    return publisher, f"url:{host}{parsed.path.rstrip('/')}"


def _identities(text: str, url: str | None, checksum: str | None = None) -> tuple[str, ...]:
    _, canonical = _url_identity(url)
    keys = ["text:" + hashlib.sha256(" ".join(fold(text).split()).encode()).hexdigest()]
    if canonical:
        keys.append(canonical)
    if checksum:
        keys.append("checksum:" + checksum)
    return tuple(keys)


def stored_evidence(db: Session, tenant: int) -> Iterator[Evidence]:
    for chunk, doc in db.execute(select(DocumentChunk, Document).join(
        Document, Document.id == DocumentChunk.document_id
    ).where(DocumentChunk.tenant_id == tenant, Document.tenant_id == tenant)):
        if doc.published_at is not None:
            host, _ = _url_identity(doc.source_url)
            yield Evidence(f"document_chunk:{chunk.id}", chunk.text, doc.published_at,
                           host, (f"document:{doc.id}", *_identities(chunk.text, doc.source_url, doc.checksum)))
    for chunk, doc in db.execute(select(KnowledgeChunk, KnowledgeDocument).join(
        KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id
    ).where(KnowledgeChunk.tenant_id == tenant, KnowledgeDocument.tenant_id == tenant,
            KnowledgeDocument.status == "ready")):
        if doc.publication_date is not None:
            host, _ = _url_identity(doc.source_url)
            origin = fold(doc.author).strip() if doc.author and doc.author.strip() else host
            linked = (f"document:{doc.source_document_id}",) if doc.source_document_id else ()
            yield Evidence(f"knowledge_chunk:{chunk.id}", chunk.content,
                           datetime.combine(doc.publication_date, datetime.min.time(), UTC), origin,
                           (f"knowledge_document:{doc.id}", *linked,
                            *_identities(chunk.content, doc.source_url, doc.checksum)))
    for news in db.scalars(select(NewsEvent).where(NewsEvent.tenant_id == tenant)):
        host, _ = _url_identity(news.url)
        # source often names an aggregator (GDELT/RSS/manual), not a publisher.
        # El texto analizado es titular + resumen: la ingesta ya guarda
        # `summary` (coste 0) y la mencion de la escasez suele estar solo en
        # el cuerpo resumido; con solo el titular este carril la perdia entera.
        # La IDENTIDAD del hecho (copias sindicadas) se sigue derivando del
        # titular, para no romper la deduplicacion por hash existente.
        summary = (news.summary or "").strip()
        text = news.title if not summary else f"{news.title}. {summary}"
        yield Evidence(f"news_event:{news.id}", text, news.date, host,
                       _identities(news.title, news.url))


def aggregate(evidence: Iterable[Evidence]) -> dict[str, dict]:
    groups: dict[str, list[Evidence]] = {theme: [] for theme in THEMES}
    for item in evidence:
        for theme in extract_themes(item.text):
            groups[theme].append(item)
    result: dict[str, dict] = {}
    for theme, items in groups.items():
        # Union by source, URL, checksum or identical text. Transitive copies
        # cannot inflate the count by switching publisher in a storage lane.
        components: list[tuple[set[str], set[str]]] = []
        for item in items:
            keys = set(item.identities)
            if item.origin:
                keys.add("origin:" + item.origin)
            origins = {item.origin} if item.origin else set()
            remaining = []
            for old_keys, old_origins in components:
                if keys & old_keys:
                    keys |= old_keys
                    origins |= old_origins
                else:
                    remaining.append((old_keys, old_origins))
            # Merging may connect a previously separate component.
            while any(keys & k for k, _ in remaining):
                disconnected = []
                for old_keys, old_origins in remaining:
                    if keys & old_keys:
                        keys |= old_keys
                        origins |= old_origins
                    else:
                        disconnected.append((old_keys, old_origins))
                remaining = disconnected
            components = [*remaining, (keys, origins)]
        dates = [i.date.replace(tzinfo=UTC) if i.date.tzinfo is None else i.date.astimezone(UTC) for i in items]
        result[theme] = {
            "evidence_ids": sorted({i.id for i in items}),
            "first_seen": min(dates) if dates else None,
            "last_seen": max(dates) if dates else None,
            "n_sources": sum(bool(origins) for _, origins in components),
        }
    return result


def refresh_signals(db: Session) -> int:
    tenant = db.info.get("tenant_id")
    if not isinstance(tenant, int):
        raise ValueError("Se requiere un espacio de trabajo")
    # Serialize refreshes on Postgres; caller owns the transaction / commit.
    from app.models import Tenant

    db.scalar(select(Tenant).where(Tenant.id == tenant).with_for_update())
    values = aggregate(stored_evidence(db, tenant))
    existing = {row.theme: row for row in db.scalars(select(BottleneckSignal).where(
        BottleneckSignal.tenant_id == tenant
    ))}
    for theme, fields in values.items():
        row = existing.get(theme)
        if row is None:
            row = BottleneckSignal(tenant_id=tenant, theme=theme)
            db.add(row)
        row.evidence_ids = fields["evidence_ids"]
        row.first_seen = fields["first_seen"]
        row.last_seen = fields["last_seen"]
        row.n_sources = fields["n_sources"]
    db.flush()
    return len(values)
