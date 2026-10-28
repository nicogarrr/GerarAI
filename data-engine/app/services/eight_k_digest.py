"""Resumen extractivo de 8-K de las compañías seguidas (cartera + watchlist).

Sin modelo ni cifras calculadas: por cada ``Item`` del 8-K se devuelve el
nombre oficial del apartado (formulario 8-K de la SEC) y las primeras frases
literales del propio texto, con el ``chunk_id`` de origen. Solo documentos con
URL oficial de SEC (``official_document``). Lectura pura: no descarga nada.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Company, Document, DocumentChunk, Position, WatchItem
from app.services.company_resolver import resolve_companies
from app.services.filing_changes import excerpt_units
from app.services.filing_intelligence import KEY, official_document

MAX_SCAN = 300
MAX_CHUNKS = 400
MAX_EXCERPTS_PER_ITEM = 2
MAX_ITEMS_PER_FILING = 8
MIN_SENTENCE = 30
MAX_SENTENCE = 600

# Nombres oficiales de los apartados del formulario 8-K, en español.
ITEM_TITLES: dict[str, str] = {
    "1.01": "Acuerdo material",
    "1.02": "Rescisión de un acuerdo material",
    "1.03": "Quiebra o administración concursal",
    "1.05": "Incidente de ciberseguridad material",
    "2.01": "Compra o venta de activos",
    "2.02": "Resultados de operaciones y situación financiera",
    "2.03": "Nueva obligación financiera",
    "2.04": "Aceleración de una obligación financiera",
    "2.05": "Costes de salidas o reestructuración",
    "2.06": "Deterioro material de activos",
    "3.01": "Aviso de exclusión de cotización o incumplimiento",
    "3.02": "Venta no registrada de valores",
    "3.03": "Modificación de derechos de los accionistas",
    "4.01": "Cambio de auditor",
    "4.02": "Cuentas anteriores que no deben usarse",
    "5.01": "Cambio de control",
    "5.02": "Cambios en directivos o consejeros",
    "5.03": "Cambios en estatutos o ejercicio fiscal",
    "5.04": "Suspensión de planes de acciones de empleados",
    "5.05": "Cambios en el código ético",
    "5.07": "Votación de los accionistas",
    "5.08": "Nominaciones al consejo",
    "6.01": "Información de titulizaciones",
    "7.01": "Divulgación Regulation FD",
    "8.01": "Otros eventos",
    "9.01": "Estados financieros y anexos",
}
# Solo estos apartados: el 8-K no tiene contenido propio relevante.
NON_MATERIAL_ONLY = {"5.07", "5.08", "7.01", "9.01"}
_ITEM = re.compile(r"^Item\s+(\d\.\d{2})\s*[.:\-–—]?\s*(.*)$", re.I)
_STOP = re.compile(r"^(?:SIGNATURES?|Pursuant to the requirements)\b", re.I)
_BOILERPLATE = re.compile(
    r"forward[- ]looking|safe harbor|incorporated (?:herein )?by reference|"
    r"the information (?:in|contained in) (?:this|the following)|"
    r"shall not be deemed|check the appropriate box|see exhibit index|"
    r"emerging growth|commission file number|"
    r"with the (?:U\.S\. )?Securities and Exchange Commission",
    re.I,
)


_DECLARED_ITEM = re.compile(r"\d\.\d{2}")


def declared_items(document: Document) -> list[dict[str, Any]]:
    """Apartados declarados en el indice EDGAR (metadata["items"], "2.02, 9.01").

    Sin texto completo (la SEC bloquea la IP del servidor, F359) son lo
    unico veraz que se puede mostrar: codigo y nombre oficial del apartado,
    sin extractos.
    """
    raw = (document.metadata_ or {}).get("items")
    if not isinstance(raw, str):
        return []
    out: list[dict[str, Any]] = []
    for code in _DECLARED_ITEM.findall(raw):
        if any(i["code"] == code for i in out):
            continue
        out.append({"code": code, "title": ITEM_TITLES.get(code, f"Apartado {code}"),
                    "official_title": None, "excerpts": []})
    return out


def tracked_company_ids(db: Session) -> dict[int, list[str]]:
    """company_id -> ["cartera", "watchlist"] para el tenant de la sesión."""
    tenant = db.info["tenant_id"]
    found: dict[int, list[str]] = {}
    for cid in db.scalars(select(Position.company_id).where(
        Position.tenant_id == tenant, Position.quantity > 0,
    )).all():
        if cid is not None:
            found.setdefault(cid, [])
            if "cartera" not in found[cid]:
                found[cid].append("cartera")
    symbols = sorted(set(db.scalars(select(WatchItem.symbol).where(WatchItem.tenant_id == tenant)).all()))
    # Lote (1-2 IN) en vez de una resolucion por simbolo de la watchlist.
    resolved, _missing = resolve_companies(db, [symbol for symbol in symbols if symbol])
    for company in resolved:
        found.setdefault(company.id, [])
        if "watchlist" not in found[company.id]:
            found[company.id].append("watchlist")
    return found


# Final de frase que NO es final de frase: inicial ("Colette M."), siglas ("U.S.") y abreviaturas.
_ABBREV_END = re.compile(
    r"(?:\b[A-Z]|\b(?:Inc|Corp|Co|Ltd|LLC|No|Nos|Mr|Mrs|Ms|Dr|Jr|Sr|St|Messrs|vs|etc|approx))\.$"
)
_OFFICIAL_TITLE_START = (
    "Entry into", "Termination of", "Completion of", "Results of Operations", "Creation of", "Triggering",
    "Costs Associated", "Material Impairments", "Notice of Delisting", "Unregistered Sales", "Material Modification",
    "Changes in Registrant", "Non-Reliance", "Changes in Control", "Departure of Directors", "Amendments to",
    "Temporary Suspension", "Amendment to", "Submission of Matters", "Shareholder Nominations", "Regulation FD",
    "Other Events", "Financial Statements", "Material Cybersecurity", "Bankruptcy", "Mine Safety",
)


# QA 10: published_at puede faltar aunque el propio nombre del filing la
# lleve (jpm-20261013.htm). Se deriva del nombre del documento o de su
# URL; una fecha invalida o ausente sigue siendo None, nunca se inventa.
# Los limites de digitos evitan falsos positivos en CIK y accession.
_FILENAME_DATE_RE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)"
)


def _filing_date_from_name(*texts: str | None) -> str | None:
    for text in texts:
        for match in _FILENAME_DATE_RE.finditer(text or ""):
            try:
                return date(
                    int(match.group(1)), int(match.group(2)), int(match.group(3))
                ).isoformat()
            except ValueError:  # p.ej. 2026-02-30: se prueba la siguiente pista
                continue
    return None


def _filed_at(document: Document) -> str | None:
    if document.published_at:
        return document.published_at.date().isoformat()
    return _filing_date_from_name(document.source_url, document.title)


def _looks_like_official_title(text: str) -> bool:
    if len(text) > 250 or not text[:1].isupper():
        return False
    return (not text.endswith(".")) or ";" in text or text.startswith(_OFFICIAL_TITLE_START)


def _rejoin_sentences(units: list[dict]) -> list[dict]:
    """Une trozos partidos tras inicial/abreviatura dentro del mismo chunk.

    ``excerpt_units`` parte en "punto + espacio + mayuscula", lo que corta
    "Colette M. Kress" o "U.S. Securities...". Una cita nunca debe empezar a
    mitad de frase.
    """
    merged: list[dict] = []
    for unit in units:
        previous = merged[-1] if merged else None
        if (previous is not None and previous["chunk_id"] == unit["chunk_id"]
                and _ABBREV_END.search(previous["text"])
                and not _ITEM.match(previous["text"]) and not _ITEM.match(unit["text"])
                and not _STOP.match(unit["text"])):
            merged[-1] = {**previous, "text": f"{previous['text']} {unit['text']}"}
        else:
            merged.append(dict(unit))
    return merged


def summarize_items(chunks: list[dict]) -> list[dict[str, Any]]:
    """Apartados del 8-K con extractos literales. Puro, sin acceso a datos."""
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    awaiting_title = False
    for unit in _rejoin_sentences(excerpt_units(chunks)):
        text = unit["text"]
        if _STOP.match(text):
            break
        heading = _ITEM.match(text)
        if heading:
            code = heading.group(1)
            if any(i["code"] == code for i in items):
                current = None
                continue
            current = {"code": code, "title": ITEM_TITLES.get(code, f"Apartado {code}"),
                       "official_title": heading.group(2).strip() or None, "excerpts": []}
            items.append(current)
            awaiting_title = current["official_title"] is None
            continue
        if awaiting_title:
            awaiting_title = False
            if current is not None and _looks_like_official_title(text):
                current["official_title"] = text  # titulo oficial en la linea siguiente: no es un extracto
                continue
        if (current is None or current["code"] == "9.01"
                or len(current["excerpts"]) >= MAX_EXCERPTS_PER_ITEM):
            continue
        if (MIN_SENTENCE <= len(text) <= MAX_SENTENCE and text[:1].isupper()
                and not _BOILERPLATE.search(text)):
            current["excerpts"].append({"text": text, "chunk_id": unit["chunk_id"]})
    return items


def is_material(items: list[dict[str, Any]]) -> bool:
    return any(item["code"] not in NON_MATERIAL_ONLY for item in items)


def _load_chunks(db: Session, document: Document) -> list[dict] | None:
    rows = db.scalars(select(DocumentChunk).where(
        DocumentChunk.tenant_id == document.tenant_id, DocumentChunk.document_id == document.id,
    ).order_by(DocumentChunk.chunk_index).limit(MAX_CHUNKS + 1)).all()
    if len(rows) > MAX_CHUNKS:
        return None
    return [{"id": r.id, "chunk_index": r.chunk_index, "text": r.text} for r in rows]


def eight_k_digest(db: Session, *, page: int = 1, page_size: int = 10) -> dict[str, Any]:
    """8-K recientes con contenido relevante de las compañías seguidas."""
    tenant = db.info.get("tenant_id")
    if tenant is None:
        raise ValueError("Tenant context required")
    tracked = tracked_company_ids(db)
    if not tracked:
        return {"status": "insufficient_data", "reason": "Sin posiciones ni watchlist.",
                "page": page, "page_size": page_size, "total": 0, "scanned": 0, "items": []}
    documents = db.scalars(select(Document).where(
        Document.tenant_id == tenant, Document.company_id.in_(tracked),
        Document.metadata_["form"].as_string() == "8-K",
    ).order_by(desc(Document.published_at).nullslast(), desc(Document.id)).limit(MAX_SCAN)).all()
    entries: list[dict[str, Any]] = []
    seen: dict[tuple[int, str], dict[str, Any]] = {}
    for document in documents:
        if document.company_id is None or not official_document(document):
            continue
        company = db.get(Company, document.company_id)
        if company is None:
            continue
        parsed_url = urlsplit(document.source_url or "")
        # Query y fragmento no identifican otro formulario SEC. Nunca por ticker:
        # dos 8-K distintos de una empresa deben seguir siendo dos entradas.
        identity = (company.id, f"{parsed_url.hostname}{parsed_url.path}")
        chunks = _load_chunks(db, document)
        previous = seen.get(identity)
        if previous is not None:
            if chunks and previous["status"] == "insufficient_data":
                items = summarize_items(chunks)
                if items and is_material(items):
                    previous.update(status="ready", items=items[:MAX_ITEMS_PER_FILING],
                                    document_id=document.id,
                                    source_url=document.source_url,
                                    filed_at=_filed_at(document) or previous["filed_at"])
                    previous.pop("reason", None)
            continue
        base = {
            "document_id": document.id, "ticker": company.ticker, "company": company.name,
            "filed_at": _filed_at(document),
            "source": "SEC", "source_url": document.source_url, "label": "OFICIAL",
            "matching": tracked[document.company_id],
            "filing_intelligence": (document.metadata_ or {}).get(KEY),
        }
        if not chunks:
            declared = declared_items(document)
            entry = {**base, "status": "insufficient_data", "items": declared,
                     "reason": ("Sin texto completo disponible; se muestran solo los apartados "
                                "declarados ante la SEC." if declared else
                                "Sin texto completo disponible; revisa el documento oficial.")}
            entries.append(entry)
            seen[identity] = entry
            continue
        items = summarize_items(chunks)
        if not items:
            declared = declared_items(document)
            entry = {**base, "status": "insufficient_data", "items": declared,
                     "reason": ("No se identificaron apartados legibles en el 8-K; se muestran "
                                "los declarados ante la SEC." if declared else
                                "No se identificaron apartados legibles en el 8-K.")}
            entries.append(entry)
            seen[identity] = entry
        elif is_material(items):
            entry = {**base, "status": "ready", "items": items[:MAX_ITEMS_PER_FILING]}
            entries.append(entry)
            seen[identity] = entry
    start = (page - 1) * page_size
    return {"status": "ready" if entries else "insufficient_data",
            "reason": None if entries else "Sin 8-K relevantes de tus compañías.",
            "page": page, "page_size": page_size, "total": len(entries),
            "scanned": len(documents), "items": entries[start:start + page_size]}
