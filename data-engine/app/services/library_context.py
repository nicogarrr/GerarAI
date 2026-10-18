"""Library doctrine with SQL-backed, tenant-scoped citation identity.

Retrieved letters are context for inference, never company financial facts.
Vector payload text, titles and URLs are not authoritative.
"""
from itertools import zip_longest

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument
from app.services.rag import RAGIndex

# Las cartas están en inglés: una pregunta en castellano se recupera también
# con los términos de inversión equivalentes. Sin LLM ni coste.
_ES_EN_TERMS: tuple[tuple[str, str], ...] = (
    ("margen de seguridad", "margin of safety"),
    ("foso", "moat competitive advantage"),
    ("ventaja competitiva", "competitive advantage moat"),
    ("valor intrínseco", "intrinsic value"),
    ("valor intrinseco", "intrinsic value"),
    ("círculo de competencia", "circle of competence"),
    ("circulo de competencia", "circle of competence"),
    ("señor mercado", "Mr. Market"),
    ("senor mercado", "Mr. Market"),
    ("largo plazo", "long term"),
    ("diversificación", "diversification"),
    ("diversificacion", "diversification"),
    ("riesgo", "risk"),
    ("ciclo de mercado", "market cycle"),
    ("burbuja", "bubble"),
    ("recompra de acciones", "share repurchase buyback"),
    ("dividendo", "dividend"),
    ("flujo de caja libre", "free cash flow"),
    ("flujo de caja", "cash flow"),
    ("calidad", "quality"),
    ("gestión", "management"),
    ("gestion", "management"),
    ("asignación de capital", "capital allocation"),
    ("asignacion de capital", "capital allocation"),
    ("inversión en valor", "value investing"),
    ("inversion en valor", "value investing"),
    ("inflación", "inflation"),
    ("inflacion", "inflation"),
    ("deuda", "debt leverage"),
    ("apalancamiento", "leverage"),
    ("paciencia", "patience"),
    ("especulación", "speculation"),
    ("especulacion", "speculation"),
)


def expand_query_en(question: str) -> str | None:
    """Términos en inglés equivalentes a los del castellano, o None si no hay."""
    lowered = (question or "").lower()
    extra: list[str] = []
    for spanish, english in _ES_EN_TERMS:
        if spanish in lowered and english not in extra:
            extra.append(english)
    return " ".join(extra) if extra else None


def retrieve_library_context(db: Session, question: str, limit: int = 3) -> list[dict]:
    tenant_id = db.info.get("tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0:
        return []
    queries = [question]
    expanded = expand_query_en(question)
    if expanded:
        queries.append(expanded)
    per_query: list[list[dict]] = []
    for query in queries:
        try:
            per_query.append(
                RAGIndex().search(
                    query,
                    ticker=None,
                    limit=20,
                    tenant_id=tenant_id,
                    entity_type="knowledge_chunk",
                )
            )
        except Exception:
            continue
    # Intercalados: la consulta original y la expandida compiten por igual.
    hits = [hit for group in zip_longest(*per_query) for hit in group if hit is not None]
    if not hits:
        return []
    contexts = []
    seen = set()
    for hit in hits:
        chunk_id = hit.get("entity_id")
        if hit.get("entity_type") != "knowledge_chunk" or type(chunk_id) is not int or chunk_id in seen:
            continue
        row = db.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id)
            .where(KnowledgeChunk.id == chunk_id, KnowledgeChunk.tenant_id == tenant_id,
                   KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.status == "ready")
        ).first()
        if not row:
            continue
        chunk, document = row
        if not chunk.content.strip() or not chunk.qdrant_point_id or str(hit.get("point_id")) != chunk.qdrant_point_id:
            continue
        seen.add(chunk_id)
        contexts.append({
            "type": "knowledge_chunk", "id": chunk.id, "chunk_id": chunk.id,
            "knowledge_document_id": document.id, "title": document.title,
            "author": document.author,
            "year": document.publication_date.year if document.publication_date else None,
            "url": document.source_url,
            "source_type": document.document_type, "page_number": chunk.page_number,
            "chunk_index": chunk.chunk_index, "text": chunk.content[:1600],
            "evidence_role": "investment_doctrine_not_company_fact",
        })
        if len(contexts) >= limit:
            break
    return contexts
