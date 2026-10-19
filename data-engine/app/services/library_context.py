"""Library doctrine with SQL-backed, tenant-scoped citation identity.

Retrieved letters are context for inference, never company financial facts.
Vector payload text, titles and URLs are not authoritative.
"""
import re
import unicodedata
from itertools import zip_longest

from sqlalchemy import or_, select
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


INVESTOR_AUTHORS = ("buffett", "munger", "graham", "marks", "klarman", "lynch", "fisher", "templeton")


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", (text or "").lower()) if not unicodedata.combining(c))


def named_investors(question: str) -> list[str]:
    folded = _fold(question)
    return [name for name in INVESTOR_AUTHORS if re.search(rf"\b{name}\b", folded)]


def _context_row(chunk, document) -> dict:
    return {
        "type": "knowledge_chunk", "id": chunk.id, "chunk_id": chunk.id,
        "knowledge_document_id": document.id, "title": document.title,
        "author": document.author,
        "year": document.publication_date.year if document.publication_date else None,
        "url": document.source_url,
        "source_type": document.document_type, "page_number": chunk.page_number,
        "chunk_index": chunk.chunk_index, "text": chunk.content[:1600],
        "evidence_role": "investment_doctrine_not_company_fact",
    }


def lexical_library_context(db: Session, question: str, *, authors: list[str], limit: int = 3) -> list[dict]:
    """Texto literal de la biblioteca (SQL, sin vectores), con filtro de autor opcional.

    Respaldo cuando la busqueda vectorial esta apagada o no trae fragmentos del
    autor nombrado: sin el, "que dicen las cartas de Buffett sobre X" respondia
    "no tengo fragmento" aunque la biblioteca tenga sus cartas.
    """
    from app.services.knowledge_chat import _terms

    tenant_id = db.info.get("tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0:
        return []
    terms = _terms(question)
    expanded = expand_query_en(question)
    if expanded:
        terms = list(dict.fromkeys([*terms, *expanded.split()]))
    terms = [t for t in terms if _fold(t) not in INVESTOR_AUTHORS and t.lower() not in {"carta", "cartas", "letter", "letters"}]
    terms = [t.replace("%", "").replace("_", "") for t in terms if len(t) > 2][:16]
    if not terms:
        return []
    statement = select(KnowledgeChunk, KnowledgeDocument).join(
        KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id
    ).where(KnowledgeChunk.tenant_id == tenant_id, KnowledgeDocument.tenant_id == tenant_id,
            KnowledgeDocument.status == "ready")
    if authors:
        statement = statement.where(or_(*[KnowledgeDocument.author.ilike(f"%{a}%") for a in authors]))
    try:
        rows = list(db.execute(statement.where(or_(*[KnowledgeChunk.content.ilike(f"%{t}%") for t in terms]))
                               .order_by(KnowledgeChunk.id).limit(200)).all())
    except Exception:
        return []
    scored = sorted(((sum(_fold(t) in _fold(c.content) for t in terms), c, d) for c, d in rows if c.content.strip()),
                    key=lambda item: -item[0])
    if not scored or scored[0][0] < (1 if authors or len(terms) == 1 else 2):
        return []
    best = scored[0][0]
    # Una sola carta no debe copar las 3 fuentes.
    out, per_doc = [], {}
    for score, chunk, document in scored:
        if score < min(2, best) or per_doc.get(document.id, 0) >= 2:
            continue
        per_doc[document.id] = per_doc.get(document.id, 0) + 1
        out.append(_context_row(chunk, document))
        if len(out) >= limit:
            break
    return out


def retrieve_library_context(db: Session, question: str, limit: int = 3, *, vector: bool = True) -> list[dict]:
    tenant_id = db.info.get("tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0:
        return []
    investors = named_investors(question)
    contexts = _vector_library_context(db, question, limit, tenant_id) if vector else []
    if investors and not any(
        any(name in _fold(str(item.get("author") or "")) for name in investors) for item in contexts
    ):
        # Pregunta por un autor concreto: sus fragmentos van primero.
        own = lexical_library_context(db, question, authors=investors, limit=limit)
        contexts = (own + [c for c in contexts if c["id"] not in {o["id"] for o in own}])[:limit] if own else contexts
    elif not contexts and not vector:
        contexts = lexical_library_context(db, question, authors=[], limit=limit)
    return contexts


def _vector_library_context(db: Session, question: str, limit: int, tenant_id: int) -> list[dict]:
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
