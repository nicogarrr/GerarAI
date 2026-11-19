"""Preguntas de Nico: extractos literales verificados, nunca respuestas generadas.

Una cita debe existir en un chunk del documento de esta empresa y tener URL
publica del propio documento. Ni el texto del claim ni su resumen son evidencia.
El emparejado tematico orienta la lectura, no afirma que la pregunta este resuelta.
"""
import re
import unicodedata
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.services.claim_scope import live_claims

QUESTIONS = (
    ("why", "¿Por qué tiene ventaja?", ("ventaja", "advantage", "barrier", "barrera")),
    ("value", "¿Qué valor aporta?", ("cliente", "customer", "benefit", "beneficio", "value", "valor")),
    ("competition", "¿Qué competencia tiene?", ("compet", "rival", "substitut", "sustitut")),
    ("ten_years", "¿Seguirá en 10 años?", ("10 years", "ten years", "diez anos", "10 anos")),
    ("pricing", "¿Tiene poder sobre el precio?", ("pricing power", "price increase", "pricing", "poder de precios", "fijacion de precios", "subida de precios")),
)


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", "".join(
        c for c in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(c)
    )).strip()


def safe_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"https", "http"} and bool(parsed.hostname) and not parsed.username


def moat_checklist(db: Session, company) -> list[dict]:
    rows = [{"id": key, "question": question, "status": "sin_evidencia", "excerpts": []}
            for key, question, _ in QUESTIONS]
    # Carga en lote de documentos y chunks (antes: db.get por evidencia en el
    # bucle anidado). El orden de recorrido y las decisiones no cambian.
    claims = list(live_claims(db, company))
    evidences = [evidence for claim in claims for evidence in claim.evidence]
    document_ids = {e.document_id for e in evidences if e.document_id}
    chunk_ids = {e.document_chunk_id for e in evidences if e.document_chunk_id}
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_(document_ids))).all()} if document_ids else {}
    chunks = {c.id: c for c in db.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))).all()} if chunk_ids else {}
    seen: set[tuple[str, int, str]] = set()
    for claim in claims:
        for evidence in claim.evidence:
            quote = (evidence.quote or "").strip()
            if len(quote) < 30 or not evidence.document_id or not evidence.document_chunk_id:
                continue
            doc = docs.get(evidence.document_id)
            chunk = chunks.get(evidence.document_chunk_id)
            if not doc or not chunk or doc.company_id != company.id or chunk.document_id != doc.id:
                continue
            if not safe_url(doc.source_url) or normalized(quote) not in normalized(chunk.text):
                continue
            # No aceptar un enlace distinto introducido por el resumen/evidencia.
            if evidence.source_url and evidence.source_url != doc.source_url:
                continue
            for row, (_, _, words) in zip(rows, QUESTIONS, strict=True):
                fingerprint = (row["id"], doc.id, normalized(quote))
                if fingerprint in seen or len(row["excerpts"]) >= 3:
                    continue
                if not any(word in normalized(quote) for word in words):
                    continue
                seen.add(fingerprint)
                row["status"] = "extractos_citados"
                row["excerpts"].append({
                    "quote": quote, "source_url": doc.source_url, "source_title": doc.title,
                    "document_id": doc.id, "chunk_id": chunk.id, "evidence_id": evidence.id,
                    "relation": evidence.evidence_type,
                    "published_at": doc.published_at.isoformat() if doc.published_at else None,
                })
    return rows
