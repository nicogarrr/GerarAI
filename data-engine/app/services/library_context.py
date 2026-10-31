"""Library doctrine with SQL-backed, tenant-scoped citation identity.

Retrieved letters are context for inference, never company financial facts.
Vector payload text, titles and URLs are not authoritative.
"""
import math
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
    ("derivados", "derivatives"),
    ("foso económico", "moat"),
    ("foso economico", "moat"),
    ("aseguradora", "insurance insurer float"),
    ("aseguradoras", "insurance insurer float"),
    ("objetivo", "goal"),
    ("inversor", "investor"),
    ("inversores", "investors"),
    ("miedo", "fear fearful"),
    ("codicia", "greed greedy"),
    ("crisis", "crisis panic"),
    ("precio justo", "fair price"),
    ("empresa maravillosa", "wonderful business"),
    ("negocio maravilloso", "wonderful business"),
    ("errores", "mistakes"),
    ("ventaja", "advantage"),
    ("rentado", "rentabilidades rentabilidad"),
    ("rentado", "return returns"),
    ("desde su inicio", "since inception"),
    ("rentabilidad", "return returns"),
    ("tipos de interés", "interest rates"),
    ("tipos de interes", "interest rates"),
    ("bonos", "bonds"),
    ("adquisiciones", "acquisitions"),
    ("sucesión", "succession"),
    ("sucesion", "succession"),
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


_LEXICAL_CANDIDATES = 2000
_PASSAGE_CHARS = 600


def _entity_terms(db: Session, question: str) -> list[str]:
    """Nombre de la empresa de los tickers que nombra la pregunta.

    Las cartas hablan de "Brookfield" o "Georgia Capital", no de BN o CGEO.L:
    sin este puente "¿qué opina Numantia de BN?" no encontraba nada.
    """
    from app.models import Company

    raw = {t for t in re.findall(r"\b[A-Z][A-Z0-9]{0,4}(?:\.[A-Z]{1,2})?\b", question or "")}
    if not raw:
        return []
    try:
        names = db.scalars(select(Company.name).where(Company.ticker.in_(sorted(raw)))).all()
    except Exception:
        return []
    out: list[str] = []
    for name in names:
        # "Brookfield Corporation" -> "Brookfield"; "Georgia Capital PLC" -> "Georgia Capital".
        words = [w for w in re.findall(r"[\w&]+", name or "") if w.lower() not in _CORPORATE_SUFFIXES]
        if words:
            out.append(" ".join(words[:2]) if len(words) > 1 and len(words[0]) < 8 else words[0])
    return out


# Palabras de charla que no apuntan a ningun pasaje ("gracias", "mi cartera hoy").
_CHAT_WORDS = frozenset(
    {"gracias", "hola", "cartera", "hoy", "manana", "dame", "noticias", "ahora", "actual", "favor", "vale", "bueno"}
)

_CORPORATE_SUFFIXES = frozenset(
    {"inc", "corp", "corporation", "co", "plc", "ltd", "limited", "sa", "ag", "nv", "se", "holdings", "group", "the"}
)


def _term_pattern(term: str) -> re.Pattern[str]:
    """Inicio de palabra: "derivative" casa con "derivatives", pero "risk" no
    casa dentro de "brisk"."""
    body = r"\s+".join(re.escape(part) for part in _fold(term).split())
    return re.compile(rf"(?<![\w]){body}")


def _window(text: str, patterns: list[re.Pattern[str]], size: int = _PASSAGE_CHARS) -> str:
    """Los ``size`` caracteres donde se concentran los terminos: el prompt
    recorta el fragmento a 600 caracteres y antes se quedaba con el principio,
    no con el pasaje que respondia."""
    compact = " ".join((text or "").split())
    if len(compact) <= size:
        return compact
    folded = _fold(compact)
    hits = sorted((m.start(), i) for i, rx in enumerate(patterns) for m in rx.finditer(folded))
    if not hits:
        return compact[:size]
    best_start, best_count = 0, -1
    for pos, _ in hits:
        start = max(0, pos - size // 4)
        count = len({i for p, i in hits if start <= p < start + size})
        if count > best_count:
            best_start, best_count = start, count
    if best_start > 0:
        space = compact.find(" ", best_start)
        best_start = space + 1 if 0 <= space < best_start + 40 else best_start
    out = compact[best_start:best_start + size]
    return ("…" if best_start > 0 else "") + out + ("…" if best_start + size < len(compact) else "")


def lexical_library_context(db: Session, question: str, *, authors: list[str], limit: int = 3) -> list[dict]:
    """Texto literal de la biblioteca (SQL, sin vectores), con filtro de autor opcional.

    Respaldo cuando la busqueda vectorial esta apagada o no trae fragmentos del
    autor nombrado: sin el, "que dicen las cartas de Buffett sobre X" respondia
    "no tengo fragmento" aunque la biblioteca tenga sus cartas.

    Puntuacion: terminos distintos ponderados por rareza (IDF sobre los
    candidatos) dentro de la mejor ventana de 600 caracteres. Antes se contaban
    apariciones sobre los 200 primeros candidatos por id, asi que en una
    biblioteca grande las cartas recientes ni se miraban.
    """
    from app.services.knowledge_chat import _terms

    tenant_id = db.info.get("tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0:
        return []
    terms = _terms(question)
    expanded = expand_query_en(question)
    entities = _entity_terms(db, question)
    if expanded:
        terms = list(dict.fromkeys([*terms, *expanded.split(), *_phrases(expanded)]))
    # Las cartas en castellano (Numantia) usan la frase tal cual: "margen de
    # seguridad", "desde su inicio".
    folded_question = _fold(question or "")
    spanish = [es for es, _en in _ES_EN_TERMS if " " in es and _fold(es) in folded_question]
    terms = list(dict.fromkeys([*entities, *spanish, *terms]))
    terms = [t for t in terms if _fold(t) not in INVESTOR_AUTHORS and t.lower() not in {"carta", "cartas", "letter", "letters"}]
    terms = [
        t.replace("%", "").replace("_", "") for t in terms
        if len(t) > 3 and _fold(t) not in _CHAT_WORDS
    ][:24]
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
                               .order_by(KnowledgeChunk.id).limit(_LEXICAL_CANDIDATES)).all())
    except Exception:
        return []
    rows = [(c, d) for c, d in rows if (c.content or "").strip()]
    if not rows:
        return []
    patterns = {t: _term_pattern(t) for t in terms}
    folded = {c.id: _fold(" ".join(c.content.split())) for c, _ in rows}
    found = {cid: {t for t, rx in patterns.items() if rx.search(txt)} for cid, txt in folded.items()}
    df = {t: sum(1 for hits in found.values() if t in hits) for t in terms}
    n = len(rows)
    # Nombres propios de la pregunta ("Brookfield", "GEICO") pesan como entidad.
    proper = {w.lower() for w in re.findall(r"(?<!^)(?<![¿¡.] )\b[A-Z][\w&]{3,}", (question or "").strip())}
    strong = {*entities, *(t for t in terms if " " in t)}
    boost = strong | {t for t in terms if t.lower() in proper}

    def score(chunk) -> tuple[float, int, bool]:
        matched = found[chunk.id]
        if not matched:
            return 0.0, 0, False
        idf = {t: math.log(1 + n / df[t]) * (1.5 if t in boost else 1.0) for t in matched}
        hits = sorted((m.start(), t) for t in matched for m in patterns[t].finditer(folded[chunk.id]))
        best = 0.0
        best_terms = 0
        for pos, _ in hits:
            window = {t for p, t in hits if pos <= p < pos + _PASSAGE_CHARS}
            value = sum(idf[t] for t in window)
            if value > best:
                best, best_terms = value, len(window)
        return best + 0.25 * sum(idf.values()), best_terms, bool(matched & strong)

    scored = sorted(((score(c), c, d) for c, d in rows), key=lambda item: -item[0][0])
    # Umbral: dos terminos distintos juntos, o una frase/entidad ("margin of
    # safety", "Brookfield"), o el autor nombrado. Una sola palabra suelta
    # ("riesgo") no basta: traia fragmentos sin relacion.
    def enough(item) -> bool:
        (_value, together, has_strong) = item[0]
        return together >= 2 or has_strong or (bool(authors) and together >= 1)

    out, per_doc = [], {}
    for item in scored:
        if item[0][0] <= 0 or not enough(item):
            continue
        _, chunk, document = item
        if per_doc.get(document.id, 0) >= 2:
            continue
        per_doc[document.id] = per_doc.get(document.id, 0) + 1
        row = _context_row(chunk, document)
        row["text"] = _window(chunk.content, [patterns[t] for t in found[chunk.id]])
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _phrases(expanded: str) -> list[str]:
    """Frases del glosario ("margin of safety") ademas de sus palabras."""
    return [english for spanish, english in _ES_EN_TERMS if english in expanded and " " in english]


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
    # Hidratacion en lote (anti N+1): una consulta para todos los candidatos
    # con los mismos filtros (tenant, documento ready); el orden y el cap se
    # siguen decidiendo al recorrer los hits.
    candidate_ids = [
        hit["entity_id"]
        for hit in hits
        if hit.get("entity_type") == "knowledge_chunk" and type(hit.get("entity_id")) is int
    ]
    hydrated: dict[int, tuple[KnowledgeChunk, KnowledgeDocument]] = {}
    if candidate_ids:
        for row in db.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id)
            .where(KnowledgeChunk.id.in_(candidate_ids), KnowledgeChunk.tenant_id == tenant_id,
                   KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.status == "ready")
        ).all():
            hydrated[row[0].id] = (row[0], row[1])
    contexts = []
    seen = set()
    for hit in hits:
        chunk_id = hit.get("entity_id")
        if hit.get("entity_type") != "knowledge_chunk" or type(chunk_id) is not int or chunk_id in seen:
            continue
        row = hydrated.get(chunk_id)
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


_OWN_NOTE_CUE_RE = re.compile(
    r"(?i)\b(?:nota|notas|apunt\w*|informe|informes|mi tesis|mis tesis|pienso|opino|mi opini[oó]n|"
    r"mis documentos|lo que (?:escrib|guard|sub)\w*)\b"
)


def company_library_context(db: Session, company, question: str, *, limit: int = 3) -> list[dict]:
    """Documentos de la biblioteca etiquetados con el ticker de la empresa.

    Las notas personales, informes sectoriales y tesis propias que el usuario
    sube con un ticker se guardan con ``KnowledgeDocument.ticker``, pero el chat
    de empresa no las leia nunca: "¿que apunte sobre la dilucion de ASTS?"
    respondia sin su propia nota. Aqui se recuperan los fragmentos de esos
    documentos que comparten terminos con la pregunta; si la pregunta habla de
    "mis notas"/"el informe" y ningun fragmento casa, se trae el principio de
    los documentos mas recientes.
    """
    from app.services.knowledge_chat import _terms

    tenant_id = db.info.get("tenant_id")
    ticker = (getattr(company, "ticker", None) or "").strip()
    if type(tenant_id) is not int or tenant_id <= 0 or not ticker:
        return []
    try:
        rows = list(
            db.execute(
                select(KnowledgeChunk, KnowledgeDocument)
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id)
                .where(
                    KnowledgeChunk.tenant_id == tenant_id,
                    KnowledgeDocument.tenant_id == tenant_id,
                    KnowledgeDocument.status == "ready",
                    KnowledgeDocument.ticker.is_not(None),
                    KnowledgeDocument.ticker.ilike(ticker),
                )
                .order_by(KnowledgeDocument.id.desc(), KnowledgeChunk.chunk_index)
                .limit(400)
            ).all()
        )
    except Exception:
        return []
    rows = [(c, d) for c, d in rows if (c.content or "").strip()]
    if not rows:
        return []
    company_words = {_fold(w) for w in re.findall(r"\w+", f"{ticker} {getattr(company, 'name', '') or ''}")}
    terms = [t for t in _terms(question) if _fold(t) not in company_words and len(t) > 3]
    expanded = expand_query_en(question)
    if expanded:
        terms = list(dict.fromkeys([*terms, *expanded.split()]))
    folded_terms = [_fold(t) for t in terms]

    def score(chunk) -> int:
        text = _fold(chunk.content)
        return sum(1 for t in folded_terms if t and t in text)

    scored = sorted(rows, key=lambda row: -score(row[0]))
    picked = [row for row in scored if score(row[0]) > 0][:limit]
    if not picked and _OWN_NOTE_CUE_RE.search(question or ""):
        seen: set[int] = set()
        for chunk, document in rows:
            if document.id not in seen:
                seen.add(document.id)
                picked.append((chunk, document))
            if len(picked) >= limit:
                break
    out = []
    for chunk, document in picked:
        row = _context_row(chunk, document)
        row["ticker"] = ticker
        row["evidence_role"] = "user_document_about_company_not_official"
        out.append(row)
    return out
