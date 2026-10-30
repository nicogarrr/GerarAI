"""Ingesta: fuente -> checksum/dedupe -> extraccion -> chunks -> vectores -> Qdrant."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.knowledge_rag import (
    SOURCE_STATUS_FAILED,
    SOURCE_STATUS_INDEXED,
    SOURCE_STATUS_PROCESSING,
    SOURCE_STATUS_QUEUED,
    KnowledgeRagParent,
    KnowledgeRagSource,
)
from app.services.knowledge_rag.chunking import ChunkConfig, chunk_document
from app.services.knowledge_rag.domain import (
    DocType,
    ExtractedDocument,
    SourceMetadata,
    payload_for_child,
)
from app.services.knowledge_rag.embedding import Embedder
from app.services.knowledge_rag.extract import SUPPORTED_EXTENSIONS
from app.services.knowledge_rag.store import KnowledgeStore
from app.services.knowledge_rag.tokens import TokenCounter

EMBED_BATCH = 5

Extractor = Callable[[Path], ExtractedDocument]


class InsufficientDisk(RuntimeError):
    """El VM va justo de disco: la ingesta se niega antes de empezar."""


class InboxPathError(ValueError):
    pass


def check_disk(path: Path, min_free_gb: float) -> None:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free_gb = shutil.disk_usage(probe).free / 1e9
    if free_gb < min_free_gb:
        raise InsufficientDisk(f"only {free_gb:.1f} GB free (< {min_free_gb} GB): ingestion refused")


def resolve_inbox_path(inbox: Path, relative: str, max_mb: int) -> Path:
    """Solo ficheros dentro del inbox; sin absolutos ni '..' ni symlinks fuera."""
    if not relative or Path(relative).is_absolute():
        raise InboxPathError("path must be relative to the knowledge inbox")
    root = inbox.resolve()
    target = (root / relative).resolve()
    if root != target and root not in target.parents:
        raise InboxPathError("path escapes the knowledge inbox")
    if not target.is_file():
        raise InboxPathError("file not found in the knowledge inbox")
    if target.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise InboxPathError(f"unsupported file type {target.suffix!r}")
    if target.stat().st_size > max_mb * 1024 * 1024:
        raise InboxPathError(f"file larger than {max_mb} MB")
    return target


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class RegisterResult:
    source: KnowledgeRagSource
    created: bool  # False = duplicado por checksum


def register_source(
    db: Session,
    *,
    path: Path,
    relative_path: str,
    meta: SourceMetadata,
    tenant_id: int | None,
) -> RegisterResult:
    meta.validate()
    sha = file_sha256(path)
    existing = db.scalar(
        select(KnowledgeRagSource).where(
            KnowledgeRagSource.sha256 == sha, KnowledgeRagSource.tenant_id == tenant_id
        )
    )
    if existing is not None:
        return RegisterResult(existing, False)
    source = KnowledgeRagSource(
        tenant_id=tenant_id,
        sha256=sha,
        title=meta.title,
        author=meta.author,
        source_uri=meta.source_uri,
        filename=relative_path,
        published_date=meta.published_date,
        as_of=meta.as_of,
        language=meta.language,
        doc_type=meta.doc_type.value,
        corpus=meta.corpus.value,
        rights=meta.rights,
        status=SOURCE_STATUS_QUEUED,
        warnings=[],
    )
    db.add(source)
    try:
        db.commit()
    except IntegrityError:
        # Subida concurrente del mismo fichero: la otra transaccion gano el unique
        # (tenant, sha256). Es un duplicado, no un error.
        db.rollback()
        winner = db.scalar(
            select(KnowledgeRagSource).where(
                KnowledgeRagSource.sha256 == sha, KnowledgeRagSource.tenant_id == tenant_id
            )
        )
        if winner is None:
            raise
        return RegisterResult(winner, False)
    db.refresh(source)
    return RegisterResult(source, True)


def metadata_from_source(source: KnowledgeRagSource) -> SourceMetadata:
    return SourceMetadata(
        title=source.title,
        source_uri=source.source_uri,
        language=source.language,
        doc_type=DocType(source.doc_type),
        rights=source.rights,
        author=source.author,
        published_date=source.published_date,
        as_of=source.as_of,
    ).validate()


def mark_failed(db: Session, source_id: int, message: str) -> None:
    """Estado terminal ``failed`` con motivo (nunca se deja 'queued' eterno)."""
    db.rollback()
    source = db.get(KnowledgeRagSource, source_id)
    if source is not None:
        source.status = SOURCE_STATUS_FAILED
        # source.error sale tal cual en la API de fuentes: los llamadores pasan
        # f"{type(exc).__name__}: {exc}" y eso puede llevar una URL con key.
        from app.core.errors import redact_secrets

        source.error = redact_secrets(message)[:2000]
        db.commit()
    db.rollback()


def index_source(
    db: Session,
    source_id: int,
    *,
    path: Path,
    store: KnowledgeStore,
    embedder: Embedder,
    extractor: Extractor,
    counter: TokenCounter,
    config: ChunkConfig,
) -> dict[str, Any]:
    """Reindexa una fuente registrada. Idempotente: limpia lo parcial antes.

    Tres fases para NO retener una conexion de BD durante Docling, embeddings ni
    Qdrant (pool pequeno): (A) transaccion corta que lee la fuente y la marca
    ``processing``; (B) trabajo pesado SIN sesion abierta, solo con valores
    planos; (C) transaccion corta que guarda padres y marca ``indexed``.
    """
    from dramatiq.middleware.time_limit import TimeLimitExceeded

    source = db.get(KnowledgeRagSource, source_id)
    if source is None:
        raise LookupError(f"knowledge source {source_id} not found")
    if source.status == SOURCE_STATUS_INDEXED:
        db.rollback()
        return {"status": "skipped", "reason": "already_indexed", "source_id": source_id}
    meta = metadata_from_source(source)
    tenant_id, sha256 = source.tenant_id, source.sha256
    source.status = SOURCE_STATUS_PROCESSING
    source.error = None
    db.commit()
    db.rollback()  # libera la conexion al pool antes de la fase B
    try:
        # --- Fase B: sin conexion de BD ---
        if file_sha256(path) != sha256:
            raise ValueError("file content no longer matches the registered sha256")
        extracted = extractor(path)
        parents, children = chunk_document(
            extracted,
            title=meta.title,
            source_sha256=sha256,
            count=counter,
            config=config,
            id_namespace=f"{tenant_id if tenant_id is not None else 'none'}:{source_id}:{sha256}",
        )
        if not children:
            raise ValueError("no chunks produced from the document")
        store.ensure_collection()
        store.delete_source(tenant_id, source_id)
        by_id = {p.id: p for p in parents}
        for i in range(0, len(children), EMBED_BATCH):
            batch = children[i : i + EMBED_BATCH]
            texts = [c.embed_text for c in batch]
            store.upsert(
                [c.id for c in batch],
                embedder.dense_docs(texts),
                embedder.sparse_docs(texts),
                [
                    payload_for_child(
                        c,
                        by_id[c.parent_id],
                        meta,
                        tenant_id=tenant_id,
                        source_id=source_id,
                        source_sha256=sha256,
                        extractor=extracted.extractor,
                    )
                    for c in batch
                ],
            )
        # --- Fase C: transaccion corta ---
        source = db.get(KnowledgeRagSource, source_id)
        if source is None:
            raise LookupError(f"knowledge source {source_id} disappeared")
        db.execute(delete(KnowledgeRagParent).where(KnowledgeRagParent.source_id == source_id))
        for p in parents:
            db.add(
                KnowledgeRagParent(
                    id=p.id,
                    tenant_id=tenant_id,
                    source_id=source_id,
                    ordinal=p.ordinal,
                    text=p.text,
                    text_sha256=p.text_sha256,
                    section_path=list(p.section_path),
                    page_start=p.page_start,
                    page_end=p.page_end,
                )
            )
        source.status = SOURCE_STATUS_INDEXED
        source.extractor = extracted.extractor
        source.parent_count = len(parents)
        source.chunk_count = len(children)
        source.warnings = list(extracted.warnings)
        source.error = None
        source.indexed_at = datetime.now(UTC)
        db.commit()
        result = {
            "status": "ok",
            "source_id": source_id,
            "parents": len(parents),
            "chunks": len(children),
            "max_chunk_tokens": max(c.token_count for c in children),
            "warnings": list(extracted.warnings),
        }
        db.rollback()
        return result
    except (Exception, TimeLimitExceeded) as exc:
        # TimeLimitExceeded es BaseException: sin listarlo la fuente quedaba en
        # ``processing`` sin error ni salida (ni la API ni el actor la
        # recuperaban). Se marca failed y se relanza para el reintento.
        mark_failed(db, source_id, f"{type(exc).__name__}: {exc}")
        raise


def parent_resolver(db: Session) -> Callable[[Sequence[str]], dict[str, tuple[str, str]]]:
    def resolve(ids: Sequence[str]) -> dict[str, tuple[str, str]]:
        if not ids:
            return {}
        rows = db.scalars(select(KnowledgeRagParent).where(KnowledgeRagParent.id.in_(list(ids))))
        return {r.id: (r.text, r.text_sha256) for r in rows}

    return resolve
