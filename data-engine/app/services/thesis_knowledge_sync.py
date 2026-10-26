"""La tesis PUBLICADA pasa a ser conocimiento consultable (Biblioteca/RAG).

Decision de producto: aprobar una tesis la da al Cerebro
como conocimiento de forma automatica; rechazarla o publicar una version
nueva retira la anterior. Solo versiones publicadas, con su version y sus
fuentes (el memo Markdown ya las trae); reversible en ambos sentidos.

Los documentos automaticos se marcan en metadata
``{"auto": "thesis", "ticker": ...}`` para localizarlos y sustituirlos sin
tocar jamas documentos subidos por el usuario. Cualquier fallo de ingesta
se loguea y NUNCA rompe la aprobacion: la decision ya esta persistida.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, KnowledgeCollection, KnowledgeDocument, ThesisVersion
from app.services.knowledge_library_service import (
    KNOWLEDGE_DOCUMENT_TYPES,
    KnowledgeLibraryService,
    _slug,
)
from app.services.thesis_memo import build_memo_markdown

logger = logging.getLogger("gerarai.thesis_knowledge_sync")

AUTO_FLAG = "thesis"
COLLECTION_NAME = "Tesis publicadas"
DOCUMENT_TYPE = "own_thesis"

assert DOCUMENT_TYPE in KNOWLEDGE_DOCUMENT_TYPES


def _auto_documents(db: Session, ticker: str) -> list[KnowledgeDocument]:
    """Documentos auto-generados de tesis de esta empresa (nada manual)."""
    return list(
        db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.metadata_["auto"].as_string() == AUTO_FLAG,
                KnowledgeDocument.metadata_["ticker"].as_string() == ticker,
            )
        ).all()
    )


def _ensure_collection(db: Session, service: KnowledgeLibraryService) -> KnowledgeCollection:
    slug = _slug(COLLECTION_NAME)
    existing = db.scalar(
        select(KnowledgeCollection).where(KnowledgeCollection.slug == slug)
    )
    if existing is not None:
        return existing
    return service.create_collection(
        db,
        name=COLLECTION_NAME,
        description="Versiones publicadas de las tesis generadas por GerarAI (automatico al aprobar).",
        collection_type="system",
    )


def _mark(document_id: int, db: Session, thesis: ThesisVersion, ticker: str) -> None:
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        return
    document.metadata_ = {
        **(document.metadata_ or {}),
        "auto": AUTO_FLAG,
        "ticker": ticker,
        "thesis_version_id": thesis.id,
    }
    db.commit()


def sync_thesis_knowledge(
    db: Session,
    company: Company,
    thesis: ThesisVersion,
    *,
    published: bool,
) -> dict:
    """Mantiene la Biblioteca al dia con la decision de aprobacion.

    ``published=True`` (aprobar): sustituye el documento automatico anterior
    por el memo de ESTA version. ``published=False`` (rechazar): retira el
    documento automatico. Nunca lanza.

    Devuelve el resultado para que la UI pueda contarlo sin inventar:
    ``{"status": "indexed"|"unchanged"|"removed"|"none"|"failed",
       "document_id": int | None}``.
    """
    try:
        return _sync(db, company, thesis, published=published)
    except Exception:
        logger.exception(
            "knowledge sync fallo para la tesis %s (%s)", thesis.id, company.ticker
        )
        return {"status": "failed", "document_id": None}


def _sync(db: Session, company: Company, thesis: ThesisVersion, *, published: bool) -> dict:
    service = KnowledgeLibraryService()
    existing = _auto_documents(db, company.ticker)
    current = next(
        (doc for doc in existing if (doc.metadata_ or {}).get("thesis_version_id") == thesis.id),
        None,
    )
    removed_this_version = False
    for document in existing:
        if published:
            # Aprobar sustituye cualquier version auto-indexada anterior.
            if document is current:
                continue
        elif (document.metadata_ or {}).get("thesis_version_id") != thesis.id:
            # Rechazar solo retira ESTA version: una version publicada mas
            # antigua sigue vigente y conserva su documento.
            continue
        if (document.metadata_ or {}).get("thesis_version_id") == thesis.id:
            removed_this_version = True
        service.delete_document(db, document)
    if not published:
        # Rechazo: retirado si existia; "none" si no habia nada que retirar.
        return {
            "status": "removed" if removed_this_version else "none",
            "document_id": None,
        }
    if current is not None:
        # Aprobacion de la misma version: idempotente, ya estaba indexada.
        return {"status": "unchanged", "document_id": current.id}
    collection = _ensure_collection(db, service)
    markdown = build_memo_markdown(db, company, thesis)
    result = service.ingest_bytes(
        db,
        title=f"Tesis {company.ticker} v{thesis.version} (publicada)",
        content=markdown.encode("utf-8"),
        filename=f"tesis-{company.ticker.lower()}-v{thesis.version}.md",
        document_type=DOCUMENT_TYPE,
        collection_id=collection.id,
        author="GerarAI",
        publication_date=thesis.updated_at.date() if thesis.updated_at else None,
        language="es",
        content_type="text/markdown",
    )
    document_id = result.get("knowledge_document_id")
    if isinstance(document_id, int):
        _mark(document_id, db, thesis, company.ticker)
    logger.info(
        "tesis %s v%s indexada como conocimiento (doc %s, estado %s)",
        company.ticker, thesis.version, document_id, result.get("status"),
    )
    return {
        "status": "indexed",
        "document_id": document_id if isinstance(document_id, int) else None,
    }
