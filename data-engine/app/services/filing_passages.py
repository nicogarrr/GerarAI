"""Pasajes de documentos de una empresa (10-K, 20-F, informes) para el Cerebro.

Antes el chat solo puntuaba los 80 primeros fragmentos de la empresa (los del
documento mas reciente, en orden) por solapamiento literal de palabras. En un
10-K real (100-300 fragmentos) la respuesta suele estar mas alla del 80 (los
MAPCs de Uber en el 160) y los primeros 5-15 fragmentos son la cabecera
inline-XBRL ("...2025-12-310001819994us-gaap:..."), que ganaba por coincidir
con "employee" o "segment". Ademas la pregunta llega en castellano y el
filing esta en ingles.

Aqui, sin vectores ni LLM (funciona con la busqueda vectorial apagada):
1. Terminos de la pregunta + equivalentes en ingles de un glosario de
   vocabulario de filings (empleados -> employees, proveedores -> suppliers...).
2. Prefiltro SQL (ILIKE) sobre TODOS los fragmentos de la empresa.
3. Puntuacion por terminos distintos ponderados por rareza (IDF sobre los
   candidatos), descartando la cabecera XBRL.
4. Se devuelve el pasaje (ventana) donde se concentran los terminos, para que
   el recorte del prompt no corte justo la frase que responde.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Company, Document, DocumentChunk

PASSAGE_CHARS = 900
MAX_CANDIDATES = 400

# Vocabulario de filings: castellano (sin tildes) -> terminos en ingles.
# Frases primero; las palabras sueltas se comparan por palabra completa.
_FILING_GLOSSARY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("centros de venta", ("sales centers",)),
    ("centros de distribucion", ("distribution centers",)),
    ("cartera de pedidos", ("backlog",)),
    ("flujo de caja libre", ("free cash flow",)),
    ("flujo de caja", ("cash flow",)),
    ("usuarios activos", ("monthly active", "active users")),
    ("base de lanzamiento", ("launch complex", "launch site")),
    ("bases de lanzamiento", ("launch complex", "launch site")),
    ("plataforma de lanzamiento", ("launch pad", "launch complex")),
    ("consejero delegado", ("chief executive officer",)),
    ("ee. uu.", ("united states", "u.s.")),
    ("ee.uu.", ("united states", "u.s.")),
    ("eeuu", ("united states", "u.s.")),
    ("estados unidos", ("united states", "u.s.")),
    ("operadores moviles", ("mobile network operators", "mnos")),
    ("cuota de mercado", ("market share",)),
    ("empleados", ("employees",)),
    ("empleado", ("employees",)),
    ("plantilla", ("employees", "workforce", "headcount")),
    ("trabajadores", ("employees", "workers")),
    ("proveedores", ("suppliers", "vendors")),
    ("proveedor", ("supplier", "vendor")),
    ("principales", ("largest", "major")),
    ("clientes", ("customers",)),
    ("cliente", ("customer",)),
    ("competidores", ("competitors", "competition")),
    ("competencia", ("competition", "competitors")),
    ("operadores", ("operators", "carriers", "mnos")),
    ("operador", ("operator", "carrier")),
    ("acuerdos", ("agreements",)),
    ("acuerdo", ("agreement",)),
    ("contratos", ("contracts",)),
    ("contrato", ("contract",)),
    ("lanzamiento", ("launch",)),
    ("lanzamientos", ("launches", "launch")),
    ("lanzo", ("launched",)),
    ("lanzar", ("launch",)),
    ("satelite", ("satellite",)),
    ("satelites", ("satellites",)),
    ("cohete", ("launch vehicle", "rocket")),
    ("cohetes", ("launch vehicle", "rockets")),
    ("ingresos", ("revenue",)),
    ("ventas", ("sales", "net sales")),
    ("beneficio", ("net income", "profit")),
    ("perdidas", ("net loss",)),
    ("deuda", ("debt", "indebtedness")),
    ("efectivo", ("cash",)),
    ("caja", ("cash",)),
    ("riesgos", ("risks", "risk")),
    ("riesgo", ("risk",)),
    ("usuarios", ("users", "consumers")),
    ("viajes", ("trips",)),
    ("pedidos", ("orders",)),
    ("conductores", ("drivers",)),
    ("repartidores", ("couriers",)),
    ("segmentos", ("segments",)),
    ("segmento", ("segment",)),
    ("patentes", ("patents",)),
    ("regulacion", ("regulation", "regulatory")),
    ("litigios", ("litigation", "legal proceedings")),
    ("demandas", ("lawsuits", "litigation")),
    ("dividendos", ("dividends",)),
    ("dividendo", ("dividend",)),
    ("recompras", ("repurchases", "repurchase")),
    ("recompra", ("repurchase",)),
    ("adquisiciones", ("acquisitions",)),
    ("adquisicion", ("acquisition",)),
    ("estacionalidad", ("seasonal", "seasonality")),
    ("estacional", ("seasonal",)),
    ("inventario", ("inventory",)),
    ("inventarios", ("inventory",)),
    ("instalaciones", ("facilities", "properties")),
    ("fabricas", ("manufacturing facilities", "factories")),
    ("sede", ("headquarters",)),
    ("aranceles", ("tariffs",)),
    ("accionistas", ("stockholders", "shareholders")),
    ("acciones", ("shares",)),
    ("dilucion", ("dilution",)),
    ("espectro", ("spectrum",)),
    ("cobertura", ("coverage",)),
    ("gobierno", ("government",)),
    ("defensa", ("defense",)),
    ("suscriptores", ("subscribers",)),
    ("margen", ("margin",)),
    ("marca", ("brand",)),
    ("productos", ("products",)),
    ("servicios", ("services",)),
    ("estrategia", ("strategy",)),
    ("ciberseguridad", ("cybersecurity",)),
    ("auditor", ("auditor",)),
    ("impuestos", ("income taxes", "tax")),
    ("pais", ("country",)),
    ("paises", ("countries",)),
    ("fabricacion", ("manufacturing",)),
    ("produccion", ("production",)),
    ("tecnologia", ("technology",)),
    ("investigacion", ("research and development",)),
    ("desarrollo", ("development",)),
)

# Palabras de pregunta que no discriminan pasajes.
_STOP = frozenset(
    (
        "que",
        "cual",
        "cuales",
        "cuanto",
        "cuantos",
        "cuanta",
        "cuantas",
        "como",
        "donde",
        "cuando",
        "quien",
        "quienes",
        "por",
        "para",
        "con",
        "sin",
        "sobre",
        "entre",
        "desde",
        "hasta",
        "segun",
        "tiene",
        "tienen",
        "tengo",
        "tenia",
        "esta",
        "estan",
        "este",
        "esta",
        "esto",
        "ese",
        "esa",
        "eso",
        "sus",
        "los",
        "las",
        "del",
        "una",
        "uno",
        "unos",
        "unas",
        "mis",
        "mio",
        "mia",
        "dice",
        "dicen",
        "mis",
        "documentos",
        "documento",
        "informe",
        "filing",
        "10-k",
        "anual",
        "annual",
        "report",
        "ano",
        "2024",
        "2025",
        "2026",
        "hay",
        "son",
        "ser",
        "fue",
        "han",
        "hace",
        "mas",
        "muy",
        "tambien",
        "pasan",
        "pasa",
        "el",
        "la",
        "lo",
        "le",
        "de",
        "en",
        "al",
        "su",
        "se",
        "mi",
        "tu",
        "ya",
        "si",
        "no",
        "ni",
        "y",
        "o",
        "e",
        "u",
        "tuvo",
        "tuvieron",
        "the",
        "and",
        "for",
        "with",
        "what",
        "how",
        "many",
        "does",
        "about",
        "from",
        "that",
        "this",
        "which",
    )
)

_XBRL_CONTEXT_RE = re.compile(r"\d{10}(?:[a-z\-]+:|\d{4}-\d{2}-\d{2})")


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", (text or "").lower()) if not unicodedata.combining(c)
    )


def is_xbrl_header(text: str) -> bool:
    """Cabecera inline-XBRL (contextos "...0001819994us-gaap:...Member2025-...").

    Es texto de maquina sin frases: nunca responde una pregunta.
    """
    return len(_XBRL_CONTEXT_RE.findall(text or "")) >= 5


def query_terms(question: str, company: Company | None = None) -> list[str]:
    """Terminos a buscar: palabras de la pregunta + traduccion de filings.

    El nombre y ticker de la empresa se quitan: aparecen en todo el filing.
    """
    folded = _fold(question)
    own = set()
    if company is not None:
        own = {w for w in re.findall(r"\w+", _fold(f"{company.ticker} {company.name or ''}")) if len(w) > 2}
    words = [
        w
        for w in re.findall(r"[\w.&-]+", folded)
        if len(w.strip(".-")) > 2 and w not in _STOP and w not in own
    ]
    terms: list[str] = []
    # Nombres propios de varias palabras ("Vision Pro", "Block 2"): pares de
    # palabras de la pregunta original, que en ingles suelen ir igual.
    raw = [w for w in re.findall(r"[\w&]+", folded)]
    for first, second in zip(raw, raw[1:], strict=False):
        if first not in _STOP and second not in _STOP and first not in own and len(first + second) > 5:
            if not any(first == s.split()[0] for s, _ in _FILING_GLOSSARY if " " in s):
                terms.append(f"{first} {second}")
    for spanish, english in _FILING_GLOSSARY:
        if " " in spanish:
            if spanish in folded:
                terms.extend(english)
        elif spanish in words:
            terms.extend(english)
    # Palabras originales: nombres propios (Neutron, Pentair), siglas (MAPCs),
    # numeros (Block 2) y cognados que coinciden en ingles.
    terms.extend(w.strip(".-") for w in words)
    return list(dict.fromkeys(t for t in terms if t))[:24]


def _term_re(term: str) -> re.Pattern[str]:
    """Palabra (o frase) completa, admitiendo plural ingles: "employee" no
    debe casar dentro de "EmployeeStockMember" ni "venta" dentro de
    "inventory"."""
    body = r"\s+".join(re.escape(part) for part in term.lower().split())
    return re.compile(rf"(?<![\w]){body}(?:s|es)?(?![\w])")


_QUANTITY_CUE_RE = re.compile(r"\b(?:cuant[oa]s?|numero|cifra|cuanto|how many|how much)\b")


@dataclass
class Passage:
    chunk: DocumentChunk
    document: Document
    text: str
    score: float


def _passage(text: str, terms: list[str], size: int = PASSAGE_CHARS) -> str:
    """Ventana de ``size`` caracteres donde aparecen mas terminos distintos."""
    compact = " ".join((text or "").split())
    if len(compact) <= size:
        return compact
    low = compact.lower()
    hits = sorted((m.start(), term) for term in terms for m in _term_re(term).finditer(low))
    best_start, best_count = 0, -1
    for pos, _ in hits:
        start = max(0, pos - size // 4)
        window = {t for p, t in hits if start <= p < start + size}
        if len(window) > best_count:
            best_start, best_count = start, len(window)
    start = best_start
    if start > 0:
        space = compact.find(" ", start)
        start = space + 1 if 0 <= space < start + 40 else start
    end = min(len(compact), start + size)
    out = compact[start:end]
    return ("…" if start > 0 else "") + out + ("…" if end < len(compact) else "")


def company_passages(db: Session, company: Company, question: str, limit: int = 4) -> list[Passage]:
    """Los ``limit`` pasajes de los documentos de la empresa que mejor responden."""
    tenant_id = db.info.get("tenant_id")
    terms = query_terms(question, company)
    if not terms:
        return []
    statement = (
        select(DocumentChunk, Document)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.company_id == company.id)
        .where(or_(*[DocumentChunk.text.icontains(t, autoescape=True) for t in terms]))
        .limit(MAX_CANDIDATES)
    )
    if tenant_id is not None:
        statement = statement.where(DocumentChunk.tenant_id == tenant_id, Document.tenant_id == tenant_id)
    rows = [(c, d) for c, d in db.execute(statement).all() if c.text and not is_xbrl_header(c.text)]
    if not rows:
        return []
    lowered = {c.id: " ".join(c.text.lower().split()) for c, _ in rows}
    patterns = {t: _term_re(t) for t in terms}
    found = {cid: {t for t, rx in patterns.items() if rx.search(txt)} for cid, txt in lowered.items()}
    df = {t: sum(1 for hits in found.values() if t in hits) for t in terms}
    n = len(rows)
    quantity = bool(_QUANTITY_CUE_RE.search(_fold(question)))

    idf = {t: math.log(1 + n / df[t]) * (1.5 if " " in t else 1.0) for t in terms if df[t]}

    def score(chunk: DocumentChunk) -> float:
        matched = found[chunk.id]
        if not matched:
            return 0.0
        txt = lowered[chunk.id]
        # Terminos juntos en la misma frase valen mas que repartidos por un
        # fragmento de 2.500 caracteres: se puntua la mejor ventana de 400.
        hits = sorted((m.start(), t) for t in matched for m in patterns[t].finditer(txt))
        best = 0.0
        for pos, _ in hits:
            window = {t for p, t in hits if pos <= p < pos + 400}
            best = max(best, sum(idf[t] for t in window))
        value = best + 0.25 * sum(idf[t] for t in matched)
        if quantity:
            # "¿Cuantos empleados?": premia la cifra pegada al termino
            # ("2,600 full-time permanent employees", "456 sales centers").
            for t in matched:
                if re.search(rf"\d[\d,.]*\s+(?:[a-z\-]+\s+){{0,3}}{patterns[t].pattern}", txt):
                    value += 2.0
                    break
        return value

    scored = sorted(
        ((score(c), c, d) for c, d in rows),
        key=lambda item: (item[0], item[2].published_at is not None, item[2].published_at or 0),
        reverse=True,
    )
    out: list[Passage] = []
    seen_text: set[str] = set()
    for value, chunk, document in scored:
        if value <= 0:
            break
        text = _passage(chunk.text, terms)
        # 10-K con pasajes repetidos (resumen de riesgos + riesgo completo).
        key = text[:160]
        if key in seen_text:
            continue
        seen_text.add(key)
        out.append(Passage(chunk=chunk, document=document, text=text, score=round(value, 3)))
        if len(out) >= limit:
            break
    return out
