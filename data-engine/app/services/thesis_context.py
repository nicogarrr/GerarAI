"""Tenant-scoped retrieved excerpts with PostgreSQL-backed citation identity."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Document, DocumentChunk
from app.services.library_context import retrieve_library_context
from app.services.rag import RAGIndex


def retrieve_thesis_context(db: Session, company: Company) -> list[dict]:
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        return []
    try:
        hits = RAGIndex().search(
            f"{company.ticker} business risks financial results regulatory filings",
            ticker=company.ticker, limit=5, tenant_id=tenant_id,
        )
    except Exception:
        return []
    # Hidratacion en lote: una consulta para todos los chunks citados, no
    # una por hit. Los filtros de tenant/empresa son los mismos.
    chunk_ids = []
    for hit in hits:
        if hit.get("entity_type") != "document_chunk":
            continue
        chunk_id = hit.get("entity_id")
        if isinstance(chunk_id, int) and chunk_id not in chunk_ids:
            chunk_ids.append(chunk_id)
    rows = {}
    if chunk_ids:
        rows = {
            chunk.id: (chunk, document)
            for chunk, document in db.execute(
                select(DocumentChunk, Document)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.id.in_(chunk_ids),
                    DocumentChunk.tenant_id == tenant_id,
                    Document.tenant_id == tenant_id,
                    Document.company_id == company.id,
                )
            )
        }
    contexts = []
    seen = set()
    for hit in hits:
        if hit.get("entity_type") != "document_chunk":
            continue
        chunk_id = hit.get("entity_id")
        if not isinstance(chunk_id, int) or chunk_id in seen:
            continue
        row = rows.get(chunk_id)
        if not row:
            continue
        chunk, document = row
        if not chunk.text.strip():
            continue
        seen.add(chunk_id)
        contexts.append({
            "text": chunk.text[:1600], "title": document.title,
            "source_type": document.source_type, "url": document.source_url,
            "document_id": document.id, "chunk_id": chunk.id,
            "chunk_index": chunk.chunk_index,
        })
    return contexts + retrieve_library_context(
        db, f"{company.ticker} investment principles capital allocation business risks"
    )
