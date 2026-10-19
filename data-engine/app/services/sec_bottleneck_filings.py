"""Carril de texto de filings SEC para Cuellos de botella (coste 0 EUR).

El carril de noticias solo ve titular+resumen y el de documentos solo lo que
se ingiere a mano: una escasez declarada en un 8-K ("supply constraints...")
no llegaba nunca al detector. Este servicio la busca DIRECTAMENTE en la
busqueda full-text oficial de la SEC (efts.sec.gov, gratuita, sin clave) y
guarda los pasajes que pasan las mismas guardas fail-closed del detector
como Document/DocumentChunk; ``refresh_bottlenecks`` (horario) los reconcilia
despues como cualquier otro documento. Varios pasajes del mismo filing son
UNA fuente (dedupe existente por documento).

Reglas:
- Sin invencion: solo se guarda texto literal del filing, con su URL oficial.
- Idempotente: un accession ya guardado no se reingiere nunca.
- Fail-closed: si la SEC falla o limita, no se ingiere nada y el estado no
  cambia; un pasaje dudoso (negacion/alivio/hipotesis) no se guarda.
- Pacing SEC: peticiones secuenciales con pausa minima, muy por debajo del
  limite de 10 req/s de fair-access.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.services.bottleneck_service import THEMES, extract_themes
from app.services.connectors.sec_edgar import ARCHIVES_URL, default_headers

logger = logging.getLogger(__name__)

EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
FORMS = "8-K,10-K,10-Q"
# Cada corrida mira solo la ventana reciente; la idempotencia por accession
# cubre los solapes entre corridas.
WINDOW_DAYS = 7
MAX_DOCS_PER_THEME = 5
MAX_PASSAGES_PER_DOC = 3
MAX_DOC_CHARS = 2_000_000
MAX_PASSAGE_CHARS = 700
REQUEST_PAUSE_SECONDS = 0.25
SOURCE_TYPE = "sec_filing"

# Terminos de escasez (ingles: los filings son en ingles) + terminos del tema.
# La consulta la hace especifica el AND con el tema; las guardas fail-closed
# de extract_themes vuelven a filtrar frase a frase lo guardado.
_SHORTAGE_TERMS = (
    '"supply constraint" OR "supply constraints" OR "capacity constraint" OR '
    '"capacity constraints" OR "shortage" OR "shortages" OR "lead time" OR "lead times"'
)
_THEME_TERMS: dict[str, str] = {
    "Semiconductores": "semiconductor OR semiconductors OR chip OR chips OR GPU OR wafer",
    "Energía": "energy OR electricity OR " + '"power grid"' + " OR utility OR utilities",
    "Minerales": "copper OR lithium OR "
    + '"rare earth"'
    + " OR "
    + '"rare earths"'
    + " OR mineral OR minerals",
    "Transporte": "shipping OR freight OR port OR ports OR logistics",
    "Centros de datos": '"data center" OR "data centers" OR "data centre" OR "data centres"',
    "Industria aeroespacial": "aerospace OR aircraft OR satellite OR satellites OR launch OR launches",
}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def theme_query(theme: str) -> str:
    """Consulta EFTS: escasez AND tema. Solo los 6 temas con mapeo curado."""
    return f"({_SHORTAGE_TERMS}) AND ({_THEME_TERMS[theme]})"


def _hit_document_url(cik: str, accession: str, filename: str) -> str:
    return f"{ARCHIVES_URL}/{int(cik)}/{accession.replace('-', '')}/{filename}"


def _html_to_text(raw: str) -> str:
    """HTML del filing -> texto plano (sin ejecutar nada: solo strip de tags)."""
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", raw))).strip()


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def matching_passages(text: str, theme: str) -> list[str]:
    """Frases del filing que el detector ya acepta para ESTE tema.

    Reutiliza extract_themes (mismas guardas: negacion, alivio, hipotesis,
    co-ocurrencia): lo que no pasaria el detector no se guarda. Sin truncar
    a medias: una frase larga se descarta, nunca se parte.
    """
    out: list[str] = []
    for sentence in _sentences(text):
        if len(sentence) > MAX_PASSAGE_CHARS:
            continue
        if theme in extract_themes(sentence):
            out.append(sentence)
        if len(out) >= MAX_PASSAGES_PER_DOC:
            break
    return out


async def _get_json(url: str, params: dict[str, str], client: httpx.AsyncClient | None) -> dict[str, Any]:
    headers = default_headers()
    if client is not None:
        response = await client.get(url, params=params, headers=headers)
    else:
        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as owned:
            response = await owned.get(url, params=params)
    if response.status_code == 429:
        raise RuntimeError("SEC EFTS rate-limited (429): no se reintenta en la misma corrida")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("SEC EFTS devolvio un JSON no objeto")
    return data


async def _get_text(url: str, client: httpx.AsyncClient | None) -> str:
    headers = default_headers()
    if client is not None:
        response = await client.get(url, headers=headers)
    else:
        async with httpx.AsyncClient(timeout=60, headers=headers, follow_redirects=True) as owned:
            response = await owned.get(url)
    if response.status_code == 429:
        raise RuntimeError("SEC Archives rate-limited (429): no se reintenta en la misma corrida")
    response.raise_for_status()
    return response.text[:MAX_DOC_CHARS]


def parse_hits(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Hits EFTS -> (url del documento, fecha, empresa, formulario, accession)."""
    out: list[dict[str, str]] = []
    hits = payload.get("hits", {}).get("hits", [])
    for hit in hits:
        source = hit.get("_source") or {}
        accession = str(source.get("adsh") or "")
        form = str(source.get("form") or "")
        file_date = str(source.get("file_date") or "")
        names = source.get("display_names") or []
        ciks = source.get("ciks") or []
        hit_id = str(hit.get("_id") or "")
        filename = hit_id.split(":", 1)[1] if ":" in hit_id else ""
        if not (accession and form and file_date and ciks and filename):
            continue
        out.append(
            {
                "accession": accession,
                "form": form,
                "file_date": file_date,
                "company": str(names[0]) if names else accession,
                "url": _hit_document_url(str(ciks[0]), accession, filename),
            }
        )
    return out


async def fetch_theme_hits(
    theme: str, *, since: datetime, client: httpx.AsyncClient | None = None
) -> list[dict[str, str]]:
    payload = await _get_json(
        EFTS_URL,
        {
            "q": theme_query(theme),
            "forms": FORMS,
            "dateRange": "custom",
            "startdt": since.date().isoformat(),
            "enddt": datetime.now(UTC).date().isoformat(),
        },
        client,
    )
    return parse_hits(payload)


def _existing_urls(db: Session, tenant: int, urls: list[str]) -> set[str]:
    if not urls:
        return set()
    return {
        url
        for url in db.scalars(
            select(Document.source_url).where(
                Document.tenant_id == tenant,
                Document.source_url.in_(urls),
            )
        )
        if url is not None
    }


async def ingest_theme(
    db: Session,
    tenant: int,
    theme: str,
    *,
    since: datetime,
    client: httpx.AsyncClient | None = None,
) -> dict[str, int]:
    """Ingiere pasajes de filings recientes para un tema. Idempotente por URL."""
    hits = await fetch_theme_hits(theme, since=since, client=client)
    known = _existing_urls(db, tenant, [h["url"] for h in hits])
    result = {"hits": len(hits), "skipped_existing": 0, "documents": 0, "passages": 0}
    for hit in hits[: MAX_DOCS_PER_THEME + sum(1 for h in hits if h["url"] in known)]:
        if result["documents"] >= MAX_DOCS_PER_THEME:
            break
        if hit["url"] in known:
            result["skipped_existing"] += 1
            continue
        await asyncio.sleep(REQUEST_PAUSE_SECONDS)
        try:
            raw = await _get_text(hit["url"], client)
        except Exception as exc:  # noqa: BLE001 - un documento que falla no frena al resto
            logger.warning("filing SEC ilegible (%s): %s", hit["url"], type(exc).__name__)
            continue
        passages = matching_passages(_html_to_text(raw), theme)
        if not passages:
            continue
        published = datetime.fromisoformat(hit["file_date"]).replace(tzinfo=UTC)
        document = Document(
            title=f"{hit['form']} · {hit['company']}",
            source_type=SOURCE_TYPE,
            source_url=hit["url"],
            published_at=published,
            checksum=hashlib.sha256(hit["accession"].encode()).hexdigest(),
            metadata_={"accession": hit["accession"], "form": hit["form"], "carril": "cuellos"},
        )
        db.add(document)
        db.flush()
        for index, passage in enumerate(passages):
            db.add(DocumentChunk(document_id=document.id, chunk_index=index, text=passage))
        result["documents"] += 1
        result["passages"] += len(passages)
    return result


async def ingest_all(
    db: Session,
    tenant: int,
    *,
    now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Una pasada por los 6 temas. Fail-closed por tema: un error deja el resto."""
    since = (now or datetime.now(UTC)) - timedelta(days=WINDOW_DAYS)
    per_theme: dict[str, Any] = {}
    for theme in THEMES:
        try:
            per_theme[theme] = await ingest_theme(db, tenant, theme, since=since, client=client)
            # Commit por tema: un fallo posterior no arrastra lo ya bueno.
            db.commit()
        except Exception as exc:  # noqa: BLE001 - fail-closed: sin ingesta, estado intacto
            # Rollback por tema: los flush parciales del tema fallido NO pueden
            # colarse en el commit del siguiente (objecion del auditor).
            db.rollback()
            per_theme[theme] = {"error": type(exc).__name__}
        await asyncio.sleep(REQUEST_PAUSE_SECONDS)
    return {"themes": per_theme, "since": since.isoformat()}
