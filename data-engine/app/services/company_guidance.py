"""Guía de la empresa (previsiones declaradas) sacada de sus propios documentos.

Caso real (8-nov-2026): el desglose por partes de los expertos dejaba el
servicio móvil directo de ASTS «infravalorado por falta de estimaciones»
porque GerarAI no guardaba ninguna previsión, aunque la nota de resultados
del 10-ago-2026 (8-K, EX-99.2) dice: «On track to achieve full year 2026
revenue guidance of $150.0 million to $200.0 million».

Regla general (nunca por emisor, sin modelo, sin red): en el texto ya
ingerido de los documentos de la empresa (notas de resultados de los 8-K/6-K,
transcripciones, informes) se buscan frases con
- una palabra de previsión (guidance, outlook, expects, anticipates, targets,
  reaffirms, on track to…),
- una magnitud (revenue, net sales, adjusted EBITDA, EBITDA, operating
  income, free cash flow, capital expenditures, EPS),
- un rango (``$X to $Y``, ``between $X and $Y``) o una cifra única con
  «approximately/about/at least», con su escala (thousand/million/billion),
- y un periodo futuro o en curso (full year 2026, fiscal 2027, Q4 2026,
  second half of 2026) respecto a la fecha del documento.
Cada previsión se guarda en ``declared_input_values`` como dato OFICIAL
(``method='extract'``, ``status='oficial'``) con la frase literal, la URL y
la fecha del documento, clave ``guidance.<magnitud>.<periodo>``; la más
reciente gana. Sin las cuatro piezas no se guarda nada: nunca se adivina.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

EXTRACTOR_VERSION = "company_guidance v1"
MAX_DOCUMENTS = 30
MAX_AGE_DAYS = 400

_CUE = re.compile(
    r"\b(guidance|outlook|expects?|expected|expecting|anticipates?|anticipated|projects?|projected|forecasts?|"
    r"targets?|targeting|reaffirm(?:s|ed|ing)?|reiterat(?:es|ed|ing)|raises?|raised|on track to|"
    r"prev[eé]|previsi[oó]n|objetivo)\b",
    re.I,
)
# Magnitud -> sus formas en el texto (orden: la más específica primero).
METRICS: tuple[tuple[str, str], ...] = (
    ("adjusted_ebitda", r"adjusted\s+ebitda"),
    ("ebitda", r"ebitda"),
    ("free_cash_flow", r"free\s+cash\s+flow"),
    ("operating_income", r"operating\s+(?:income|profit)"),
    ("capex", r"capital\s+expenditures?|capex"),
    ("eps", r"(?:diluted\s+)?(?:earnings|eps)\s+per\s+(?:diluted\s+)?share|\beps\b"),
    ("revenue", r"(?:total\s+)?(?:net\s+)?revenues?|net\s+sales|total\s+sales|\bsales\b|ingresos"),
)
_METRIC_RE = [(key, re.compile(r"\b(?:" + pat + r")\b", re.I)) for key, pat in METRICS]
_CCY = r"(?P<ccy>US\$|C\$|CA\$|A\$|\$|€|£|USD\s?|CAD\s?|EUR\s?|GBP\s?)"
_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_SCALE = r"(?:\s*(thousand|million|billion|mn|bn|m|b)\b)?"
_RANGE = re.compile(
    r"(?:between\s+)?" + _CCY + r"\s?" + _NUM + _SCALE + r"\s*(?:to|and|-|–|—)\s*(?:" + _CCY.replace("ccy", "ccy2")
    + r")?\s?" + _NUM + _SCALE,
    re.I,
)
_SINGLE = re.compile(
    r"\b(approximately|about|around|roughly|at least|of|exceed(?:ing)?|over)\s+" + _CCY + r"\s?" + _NUM + _SCALE,
    re.I,
)
_YEAR_PERIOD = re.compile(
    r"\b(?:(?P<half>first|second)\s+half\s+(?:of\s+)?(?:fiscal\s+(?:year\s+)?)?(?P<hy>20\d{2})"
    r"|(?P<q>first|second|third|fourth)\s+quarter\s+(?:of\s+)?(?:fiscal\s+(?:year\s+)?)?(?P<qy>20\d{2})"
    r"|q(?P<qn>[1-4])\s*(?:fy)?'?(?P<qny>20\d{2})"
    r"|(?:full[\s-]year|fiscal(?:\s+year)?|fy|year)\s*'?(?P<fy>20\d{2})"
    r"|(?P<fy2>20\d{2})\s+(?:full[\s-]year|fiscal\s+year|annual))\b",
    re.I,
)
_QUARTERS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_SCALES = {"thousand": Decimal(1_000), "million": Decimal(1_000_000), "mn": Decimal(1_000_000),
           "m": Decimal(1_000_000), "billion": Decimal(1_000_000_000), "bn": Decimal(1_000_000_000),
           "b": Decimal(1_000_000_000)}
_CURRENCIES = {"US$": "USD", "$": "USD", "USD": "USD", "C$": "CAD", "CA$": "CAD", "CAD": "CAD",
               "A$": "AUD", "€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP"}


@dataclass(frozen=True)
class Guidance:
    metric: str
    period: str  # fy2026 | h2_2026 | q4_2026
    year: int
    low: Decimal | None
    base: Decimal
    high: Decimal | None
    currency: str
    quote: str
    period_read: str = "explicito"

    @property
    def input_key(self) -> str:
        return f"guidance.{self.metric}.{self.period}"


def _amount(num: str, scale: str | None, metric: str) -> Decimal:
    value = Decimal(num.replace(",", ""))
    if metric == "eps":
        return value  # por acción: sin escala
    return value * _SCALES.get((scale or "").lower(), Decimal(1))


_BARE_YEAR = re.compile(r"(?<![\d-])(20\d{2})(?![\d-])")
# «compared with fourth quarter 2025», «up from $X in 2025»: el periodo de comparación no es el previsto.
_COMPARISON = re.compile(r"\b(?:compared\s+(?:with|to)|versus|vs\.?|(?:up|down)\s+from|from)\s+[^,.;]*", re.I)
# Fechas de publicación «(October 22, 2026)» y normas «ASU 2016-09»: no son periodos.
_DATED = re.compile(r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},\s*20\d{2}", re.I)


def _period_end(key: str) -> date:
    kind, year = key.split("_")[0] if "_" in key else key[:2], int(key[-4:])
    if kind.startswith("q"):
        month = int(kind[1]) * 3
        return date(year, month, 30 if month in (6, 9) else 31)
    if kind == "h1":
        return date(year, 6, 30)
    return date(year, 12, 31)
_CURRENT_YEAR = re.compile(r"\b(full[\s-]year|annual|for the year|remainder of the year)\b", re.I)


def _explicit_periods(text: str) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for m in _YEAR_PERIOD.finditer(text):
        if m.group("hy"):
            year = int(m.group("hy"))
            found.append((f"h{1 if m.group('half').lower() == 'first' else 2}_{year}", year))
        elif m.group("qy"):
            year = int(m.group("qy"))
            found.append((f"q{_QUARTERS[m.group('q').lower()]}_{year}", year))
        elif m.group("qny"):
            year = int(m.group("qny"))
            found.append((f"q{m.group('qn')}_{year}", year))
        else:
            year = int(m.group("fy") or m.group("fy2"))
            found.append((f"fy{year}", year))
    return found


def _period(text: str, published: date, *, heading: tuple[str, int] | None = None) -> tuple[str, int, str] | None:
    """(clave, año, cómo se leyó) del periodo de la previsión, o None si no hay o es ambiguo.

    Por orden: periodo explícito (full year 2026, Q4 2026, second half of 2026);
    año suelto («2026 cash capital expenditures»); el título de la sección
    («Fourth Quarter 2026 Guidance» antes de las viñetas); «full-year/annual»
    sin año = el ejercicio del documento (se marca como leído así)."""
    text = _COMPARISON.sub(" ", text)
    explicit = [p for p in _explicit_periods(text) if _period_end(p[0]) >= published]
    if explicit:
        keys = {p[0] for p in explicit}
        return (explicit[0][0], explicit[0][1], "explicito") if len(keys) == 1 else None
    if _explicit_periods(text) and heading is None:
        return None  # solo periodos pasados: es un resultado
    text = _DATED.sub(" ", text)
    bare = {int(y) for y in _BARE_YEAR.findall(text) if int(y) >= published.year}
    if len(bare) == 1:
        year = bare.pop()
        return f"fy{year}", year, "año_suelto"
    if bare:
        return None
    if heading is not None:
        return heading[0], heading[1], "titulo_de_seccion"
    if _CURRENT_YEAR.search(text):
        return f"fy{published.year}", published.year, "ejercicio_del_documento"
    return None


def sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text or "").strip()
    # Viñetas y frases: «.», «;», «•», «o» de viñeta pegada no parten cifras con decimales.
    parts = re.split(r"(?<=[.;!?])\s+(?=[A-Z“\"(•])|\s*[•▪●]\s*", flat)
    return [p.strip() for p in parts if 20 <= len(p.strip()) <= 1200]


_PAST = re.compile(
    r"\b(was|were|totaled|totalled|increased|decreased|grew|reached|backlog|reported|achieved|generated|"
    r"recorded|delivered|ended|compared)\b",
    re.I,
)
WINDOW_BEFORE = 220
HEADING_REACH = 8  # viñetas bajo «Fourth Quarter 2026 Guidance»
WINDOW_AFTER = 100


def _window(sentence: str, start: int, end: int) -> tuple[str, int]:
    """Trozo de la frase alrededor de la cifra (la cita siempre la contiene)."""
    lo = max(0, start - WINDOW_BEFORE)
    hi = min(len(sentence), end + WINDOW_AFTER)
    if lo > 0:
        space = sentence.find(" ", lo)
        lo = space + 1 if 0 <= space < start else lo
    if hi < len(sentence):
        space = sentence.rfind(" ", end, hi)
        hi = space if space > end else hi
    return sentence[lo:hi].strip(), start - lo


def _metric_before(window: str, pos: int) -> tuple[str, int] | None:
    best: tuple[int, str, int] | None = None
    for key, rx in _METRIC_RE:
        for m in rx.finditer(window, 0, pos):
            distance = pos - m.end()
            if distance <= 120 and (best is None or distance < best[0]):
                best = (distance, key, m.end())
    return (best[1], best[2]) if best else None


def extract_guidance(text: str, *, published: date) -> list[Guidance]:
    """Previsiones declaradas en ``text`` (deterministas, sin modelo)."""
    out: list[Guidance] = []
    seen: set[tuple[str, str]] = set()
    heading: tuple[str, int] | None = None
    heading_age = 99
    for sentence in sentences(text):
        heading_age += 1
        if re.search(r"\b(guidance|outlook)\b", sentence, re.I) and not _RANGE.search(sentence) and len(sentence) <= 200:
            explicit = [p for p in _explicit_periods(sentence) if _period_end(p[0]) >= published]
            if len({p[0] for p in explicit}) == 1:
                heading, heading_age = explicit[0], 0
                continue
        if not _CUE.search(sentence):
            continue
        found: list[tuple[re.Match[str], bool]] = [(m, True) for m in _RANGE.finditer(sentence)]
        if not found:
            found = [(m, False) for m in _SINGLE.finditer(sentence)]
        for m, is_range in found:
            window, pos = _window(sentence, m.start(), m.end())
            metric_hit = _metric_before(window, pos)
            if re.match(r"\s*per\s+(?:diluted\s+)?share", sentence[m.end():m.end() + 30], re.I):
                metric_hit = ("eps", metric_hit[1] if metric_hit else pos)
            if metric_hit is None:
                continue
            metric, metric_end = metric_hit
            if metric in ("eps", "revenue", "operating_income", "free_cash_flow") and re.search(
                    r"\b(?:adjusted|non-gaap)\b", window[max(0, metric_end - 60):pos], re.I):
                metric = f"adjusted_{metric}"
            between = window[metric_end:pos]
            if _PAST.search(between) or re.match(r"\W*(?:was|were|has been)\b", sentence[m.end():m.end() + 20], re.I):
                continue  # un resultado o un backlog, no una previsión
            cue = [c for c in _CUE.finditer(window) if c.start() < pos + len(m.group(0))]
            if not cue:
                continue
            period = _period(window, published, heading=heading if heading_age <= HEADING_REACH else None)
            if period is None and _CURRENT_YEAR.search(window[:pos]) and not _explicit_periods(
                    _COMPARISON.sub(" ", window)):
                # «annual / full-year guidance» sin año: el ejercicio en curso del documento.
                period = (f"fy{published.year}", published.year, "ejercicio_del_documento")
            if period is None:
                continue
            if is_range:
                scale_hi = m.group(6)
                lo = _amount(m.group(2), m.group(3) or scale_hi, metric)
                hi = _amount(m.group(5), scale_hi or m.group(3), metric)
                if hi < lo:
                    continue
                low, base, high = lo, (lo + hi) / 2, hi
            else:
                low, base, high = None, _amount(m.group(3), m.group(4), metric), None
            if base <= 0:
                continue
            key = (metric, period[0])
            if key in seen:
                continue
            seen.add(key)
            currency = _CURRENCIES.get(re.sub(r"\s", "", m.group("ccy") or "").upper(), "USD")
            out.append(Guidance(metric=metric, period=period[0], year=period[1], low=low, base=base, high=high,
                                currency=currency, quote=window, period_read=period[2]))
    return out


def _published(doc: Any) -> date | None:
    value = getattr(doc, "published_at", None)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def refresh_company_guidance(db: Any, company: Any, tenant_id: int, *, today: date | None = None) -> dict[str, Any]:
    """Extrae la guía de los documentos ingeridos y la guarda (la más reciente por clave)."""
    from sqlalchemy import select

    from app.models.entities import Document, DocumentChunk
    from app.services.declared_input_service import DeclaredInput, DeclaredInputService

    today = today or date.today()
    docs = db.scalars(
        select(Document)
        .where(Document.tenant_id == tenant_id, Document.company_id == company.id,
               Document.retention_tombstoned_at.is_(None), Document.published_at.is_not(None))
        .order_by(Document.published_at.desc(), Document.id.desc())
        .limit(MAX_DOCUMENTS)
    ).all()
    latest: dict[str, tuple[Guidance, Any, date]] = {}
    for doc in docs:
        published = _published(doc)
        if published is None or (today - published).days > MAX_AGE_DAYS:
            continue
        chunks = db.scalars(
            select(DocumentChunk.text)
            .where(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index)
        ).all()
        for item in extract_guidance(" ".join(c or "" for c in chunks), published=published):
            if item.input_key not in latest:  # documentos del más reciente al más antiguo
                latest[item.input_key] = (item, doc, published)
    service = DeclaredInputService()
    stored: list[dict[str, Any]] = []
    for key, (item, doc, published) in sorted(latest.items()):
        url = (doc.source_url or "").strip() or None
        declared = DeclaredInput(
            input_key=key, segment_key="", low=item.low, base=item.base, high=item.high,
            unit=item.currency if item.metric != "eps" else f"{item.currency}/share",
            method="extract", source_url=url, source_quote=item.quote,
            document_id=doc.id, as_of=published,
            metadata={"kind": "company_guidance", "metric": item.metric, "period": item.period,
                      "period_read": item.period_read,
                      "extractor": EXTRACTOR_VERSION, "document_title": doc.title or ""},
        )
        if service.validate(declared):
            continue
        result = service.upsert(db, company=company, tenant_id=tenant_id, item=declared)
        stored.append({"key": key, "action": result.reason, "base": str(item.base), "as_of": published.isoformat()})
    return {"documents": len(docs), "guidance": stored}
