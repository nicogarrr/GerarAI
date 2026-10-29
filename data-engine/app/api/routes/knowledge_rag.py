"""API del RAG de conocimiento profesional (cartas, libros, memos).

Apagada por defecto (KNOWLEDGE_RAG_ENABLED). No sube bytes: la ingesta nombra un
fichero RELATIVO al inbox del servidor, que el actor lee tras comprobar disco.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.models.knowledge_rag import KnowledgeRagSource
from app.services.knowledge_rag import query_translation, runtime
from app.services.knowledge_rag.domain import DocType, SourceMetadata, SourceMetadataError
from app.services.knowledge_rag.ingest import (
    InboxPathError,
    InsufficientDisk,
    check_disk,
    mark_failed,
    parent_resolver,
    register_source,
    resolve_inbox_path,
)
from app.services.knowledge_rag.retrieval import search_knowledge
from app.services.knowledge_rag.store import SearchFilters

router = APIRouter()
_logger = logging.getLogger(__name__)


def _enabled():
    try:
        return runtime.require_enabled()
    except runtime.KnowledgeRagDisabled as exc:
        raise HTTPException(status_code=503, detail="Knowledge RAG is disabled") from exc


class SourceCreate(BaseModel):
    path: str = Field(min_length=1, max_length=500, description="Relativo al inbox del servidor")
    title: str = Field(min_length=1, max_length=500)
    source_uri: str = Field(min_length=1, max_length=1000)
    language: Literal["en", "es"]
    doc_type: DocType
    rights: Literal["public_domain", "open_license", "owner_licensed", "private_use", "unknown"] = "unknown"
    author: str | None = Field(default=None, max_length=300)
    published_date: date | None = None
    as_of: date | None = None


class QueryRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=6, ge=1, le=20)
    corpus: Literal["evergreen", "dated", "any"] = "evergreen"
    authors: list[str] = Field(default_factory=list, max_length=20)
    languages: list[Literal["en", "es"]] = Field(default_factory=list)
    doc_types: list[DocType] = Field(default_factory=list)
    source_ids: list[int] = Field(default_factory=list, max_length=50)
    published_from: date | None = None
    published_to: date | None = None
    as_of_from: date | None = None
    as_of_to: date | None = None
    include_context: bool = True


def _source(row: KnowledgeRagSource) -> dict:
    return {
        "id": row.id,
        "sha256": row.sha256,
        "title": row.title,
        "author": row.author,
        "doc_type": row.doc_type,
        "corpus": row.corpus,
        "language": row.language,
        "rights": row.rights,
        "status": row.status,
        "extractor": row.extractor,
        "parents": row.parent_count,
        "chunks": row.chunk_count,
        "warnings": row.warnings or [],
        "error": row.error,
        "indexed_at": row.indexed_at.isoformat() if row.indexed_at else None,
    }


@router.get("/sources")
def list_sources(db: Session = Depends(get_db)) -> list[dict]:
    _enabled()
    rows = db.scalars(select(KnowledgeRagSource).order_by(KnowledgeRagSource.id.desc()).limit(200))
    return [_source(r) for r in rows]


@router.get("/sources/{source_id}")
def get_source(source_id: int, db: Session = Depends(get_db)) -> dict:
    _enabled()
    row = db.get(KnowledgeRagSource, source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return _source(row)


@router.post("/sources")
def create_source(payload: SourceCreate, db: Session = Depends(get_db)) -> dict:
    settings = _enabled()
    try:
        path = resolve_inbox_path(
            settings.knowledge_rag_inbox_dir, payload.path, settings.knowledge_rag_max_file_mb
        )
        check_disk(settings.knowledge_rag_inbox_dir, settings.knowledge_rag_min_free_gb)
        meta = SourceMetadata(
            title=payload.title.strip(),
            source_uri=payload.source_uri.strip(),
            language=payload.language,
            doc_type=payload.doc_type,
            rights=payload.rights,
            author=(payload.author or "").strip() or None,
            published_date=payload.published_date,
            as_of=payload.as_of,
        )
        result = register_source(
            db, path=path, relative_path=payload.path, meta=meta, tenant_id=db.info.get("tenant_id")
        )
    except (InboxPathError, SourceMetadataError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InsufficientDisk as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc
    source = result.source
    if not result.created:
        if source.status != "failed" and not _processing_abandoned(source):
            return {**_source(source), "deduplicated": True, "requeued": False}
        # Reintento explicito y seguro: mismos bytes de una fuente fallida.
        source.filename = payload.path
        source.status = "queued"
        source.error = None
        db.commit()
    return {**_source(_dispatch(db, source)), "deduplicated": not result.created, "requeued": not result.created}


# El actor corta cada entrega a INGEST_TIME_LIMIT_MS (1 h); pasado el doble, un
# ``processing`` sin actividad es un proceso muerto (SIGKILL/OOM), no trabajo vivo.
PROCESSING_ABANDONED_AFTER = timedelta(milliseconds=2 * runtime.INGEST_TIME_LIMIT_MS)


def _processing_abandoned(source: KnowledgeRagSource, now: datetime | None = None) -> bool:
    if source.status != "processing":
        return False
    touched = source.updated_at
    if touched is None:
        return False
    if touched.tzinfo is None:
        touched = touched.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - touched > PROCESSING_ABANDONED_AFTER


def _dispatch(db: Session, source: KnowledgeRagSource) -> KnowledgeRagSource:
    source_id = source.id
    try:
        from app.workers.knowledge_rag_actors import ingest_knowledge_source

        ingest_knowledge_source.send(
            source_id, tenant_id=db.info.get("tenant_id"), user_id=db.info.get("user_id")
        )
    except Exception as exc:
        _logger.exception("knowledge ingest dispatch failed")
        mark_failed(db, source_id, f"Queue dispatch failed: {type(exc).__name__}")
        raise HTTPException(status_code=503, detail="Ingestion queue is unavailable") from exc
    refreshed = db.get(KnowledgeRagSource, source_id)
    return refreshed if refreshed is not None else source


@router.post("/query")
async def query(payload: QueryRequest, db: Session = Depends(get_db)) -> dict:
    settings = _enabled()
    tenant_id = db.info.get("tenant_id")
    tenant_info = dict(db.info)
    worker_bind = db.get_bind()
    db.rollback()  # libera la conexion (lookup de tenant de get_db) antes de embeddings/Qdrant
    filters = SearchFilters(
        corpus=payload.corpus,
        authors=tuple(payload.authors),
        languages=tuple(payload.languages),
        doc_types=tuple(d.value for d in payload.doc_types),
        source_ids=tuple(payload.source_ids),
        published_from=payload.published_from,
        published_to=payload.published_to,
        as_of_from=payload.as_of_from,
        as_of_to=payload.as_of_to,
    )

    # F372: si la pregunta parece espanol se busca tambien con su traduccion
    # al ingles. Sin LLM disponible degrada a solo la original, con nota.
    query_variants: list[str] = []
    translation_notes: list[str] = []
    if settings.knowledge_rag_query_translation:
        variant, note = await query_translation.english_variant(payload.query, settings=settings)
        if variant:
            query_variants.append(variant)
        if note:
            translation_notes.append(note)

    def run():
        with SessionLocal(bind=worker_bind) as worker_db:
            worker_db.info.update(tenant_info)
            return search_knowledge(
                payload.query,
                tenant_id=tenant_id,
                store=runtime.make_store(settings),
                embedder=runtime.make_embedder(settings),
                resolve_parents=parent_resolver(worker_db),
                filters=filters,
                top_k=payload.top_k,
                candidates=settings.knowledge_rag_candidates,
                postprocessors=runtime.make_postprocessors(settings, payload.top_k * 2),
                rrf_k=settings.rag_rrf_k,
                dense_weight=settings.rag_dense_weight,
                sparse_weight=settings.rag_sparse_weight,
                query_variants=query_variants,
            )

    try:
        result = await run_in_threadpool(run)
    except Exception as exc:
        _logger.exception("knowledge query failed")
        raise HTTPException(status_code=503, detail="Knowledge index unavailable") from exc
    return {
        "query": result.query,
        "query_variants": result.query_variants,
        "citations": [c.public(include_context=payload.include_context) for c in result.citations],
        "context": result.context if payload.include_context else None,
        "dropped_unverified": result.dropped_unverified,
        "abstain": not result.citations,
        "notes": [*translation_notes, *result.notes],
    }


@router.get("/status")
def status() -> dict:
    s = get_settings()
    return {
        "enabled": s.knowledge_rag_enabled,
        "collection": s.knowledge_rag_collection,
        "reranker": s.knowledge_rag_reranker_model or None,
        "child_max_tokens": s.knowledge_rag_child_max_tokens,
    }
