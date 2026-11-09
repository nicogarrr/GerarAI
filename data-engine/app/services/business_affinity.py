"""Afinidad de negocio entre emisores por la descripción del informe anual (regla «afinidad-negocio-v1»).

Un código SIC es grueso: 3663 junta satélites con equipos de red, 3812 junta navegación espacial con
electrónica de defensa. Esta regla compara lo que cada emisor dice de sí mismo en la sección de negocio de su
informe anual en la SEC (10-K «Item 1. Business»; 20-F «Item 4. Information on the Company»):

1. Texto: la sección de negocio del último informe anual (fuente gratis: ``data.sec.gov/submissions`` →
   documento principal del 10-K/20-F en ``www.sec.gov/Archives``).
2. Vector TF-IDF de cada emisor dentro del corpus del MISMO grupo de industria (tf sublineal; solo términos que
   aparecen en al menos ``MIN_DF`` documentos, para que un nombre propio no cuente; sin el propio nombre).
3. Afinidad = coseno entre los dos vectores (0–1). Para cada emisor se guardan los más afines del grupo —el
   cuartil superior, entre ``MIN_KEEP`` y ``MAX_KEEP``— en ``Company.factor_tags`` como ``afin:<CIK>:<coseno>``
   (mismo patrón que ``sic:nnnn``), para que la valoración no dependa de la red.

Uso (``pre_revenue_valuation.mature_peers``): dentro del grupo SIC (o del mismo SIC), primero los afines del
emisor y de ellos los de capitalización más cercana; si no reúnen comparables maduros suficientes, la capa SIC de
antes, y la ficha dice qué capa se usó. Sin descripción (sin informe anual en la SEC), el emisor no tiene afines y
se usa la capa SIC. General: nada depende del emisor ni de una lista de palabras del sector.
"""
from __future__ import annotations

import html as _html
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from typing import Any

RULE = "afinidad-negocio-v1"
MIN_DF = 2
MIN_KEEP = 8
MAX_KEEP = 24
TAG_PREFIX = "afin:"
MAX_SECTION_CHARS = 80_000
MIN_SECTION_CHARS = 5_000
ANNUAL_FORMS = ("10-K", "20-F", "10-K405", "10-KT")
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

# Palabras vacías del inglés y del lenguaje genérico de un informe anual (no de ningún sector).
_STOP = frozenset(["about", "above", "after", "again", "against", "also", "among", "amount", "amounts", "annual", "another", "any", "applicable", "approximately", "april", "area", "areas", "august", "available", "based", "because", "been", "before", "being", "below", "between", "both", "business", "businesses", "call", "called", "capital", "certain", "company", "company's", "companies", "continue", "continued", "could", "current", "currently", "customer", "customers", "december", "development", "during", "each", "early", "either", "employees", "ended", "ending", "entity", "every", "expect", "expected", "february", "fiscal", "following", "form", "from", "further", "future", "generally", "going", "growth", "have", "having", "here", "however", "include", "included", "includes", "including", "increase", "information", "interest", "into", "item", "january", "july", "june", "known", "large", "later", "less", "like", "likely", "made", "make", "management", "many", "march", "market", "markets", "material", "more", "most", "much", "must", "name", "need", "new", "non", "november", "number", "october", "offer", "offered", "offering", "offerings", "only", "operate", "operating", "operations", "order", "other", "others", "otherwise", "over", "part", "particular", "percent", "period", "periods", "plan", "plans", "primarily", "product", "products", "provide", "provided", "provides", "providing", "purpose", "quarter", "rate", "related", "report", "reported", "require", "required", "requirements", "result", "results", "revenue", "revenues", "same", "section", "september", "service", "services", "several", "shall", "should", "significant", "since", "some", "such", "support", "than", "that", "their", "them", "then", "there", "these", "they", "third", "this", "those", "three", "through", "time", "times", "total", "under", "united", "upon", "used", "uses", "using", "various", "very", "well", "were", "what", "when", "where", "whether", "which", "while", "will", "with", "within", "without", "would", "year", "years", "your", "billion", "million", "thousand", "approximately", "inc", "corporation", "corp", "llc", "ltd", "plc", "holdings", "group", "subsidiaries", "subsidiary", "annual", "registrant", "registrants", "filing", "filings", "refer", "see", "note", "notes", "table", "contents", "page", "pages", "part", "item", "items", "financial", "statements", "risk", "risks", "factors", "forward", "looking", "statement", "statements", "state", "states", "america", "american", "international", "global", "world", "worldwide", "first", "second", "one", "two", "four", "five", "six", "seven", "eight", "nine", "ten"])
_WORD = re.compile(r"[a-z][a-z0-9\-]{3,}")
_DROP = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_BLOCK = re.compile(r"<(br|/p|/div|/tr|/li|/h[1-6]|/table)\b[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_SEP = r"[\s\.\:\-–—]*"


def _w(word: str) -> str:
    """Una palabra de encabezado tolerando un espacio entre letras («B USINESS», letras en otro <span>)."""
    return r"\s?".join(re.escape(ch) for ch in word)


def _heading(*words: str) -> str:
    return r"^[ \t]*" + _SEP.join([_w("item"), *words]) + r"\b"


# Encabezados (a principio de línea, no las referencias en mitad de una frase): 10-K Item 1 → Item 1A/1B/1C/2;
# 20-F Item 4 → Item 4A/5.
_STARTS = (re.compile(_heading("1", _w("business")), re.I | re.M),
           re.compile(_heading("4", _w("information"), _w("on"), _w("the"), _w("company")), re.I | re.M))
_ENDS = (re.compile(_heading("(1a|1b|1c|2)", "(" + "|".join(_w(x) for x in ("risk", "unresolved", "cyber", "propert")) + ")"),
                    re.I | re.M),
         re.compile(_heading("(4a|5)", "(" + "|".join(_w(x) for x in ("unresolved", "operating")) + ")"), re.I | re.M))
#: Sin encabezados (un 20-F con índice de referencias cruzadas): se usa el documento entero, recortado.
MAX_DOCUMENT_CHARS = 250_000


def plain_text(raw: str) -> str:
    """HTML/iXBRL → texto plano con un salto de línea por bloque (sin etiquetas ni entidades)."""
    text = _TAG.sub(" ", _BLOCK.sub("\n", _DROP.sub(" ", raw or "")))
    text = _html.unescape(text).replace("\xa0", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*", "\n", text))


def business_section(text: str) -> str | None:
    """La sección de negocio más larga entre un encabezado de inicio y el siguiente de final (el índice, que es
    corto, no gana)."""
    best = ""
    for start_re, end_re in zip(_STARTS, _ENDS, strict=True):
        for m in start_re.finditer(text):
            end = end_re.search(text, m.end())
            body = text[m.end(): end.start()] if end else ""
            if len(body) > len(best):
                best = body
    best = best[:MAX_SECTION_CHARS]
    return best if len(best) >= MIN_SECTION_CHARS else None


def tokens(text: str, drop: Iterable[str] = ()) -> list[str]:
    dropped = {d.lower() for d in drop}
    return [w.strip("-") for w in _WORD.findall((text or "").lower())
            if w.strip("-") not in _STOP and w.strip("-") not in dropped and not w[0].isdigit()]


def name_words(name: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", str(name or "").lower()) if len(w) >= 3}


def vectors(docs: Mapping[Any, list[str]], min_df: int = MIN_DF) -> dict[Any, dict[str, float]]:
    """Vector TF-IDF normalizado de cada documento dentro del corpus (tf sublineal, idf suavizado)."""
    df: Counter[str] = Counter()
    for toks in docs.values():
        df.update(set(toks))
    n = len(docs)
    out: dict[Any, dict[str, float]] = {}
    for key, toks in docs.items():
        vec = {t: (1.0 + math.log(c)) * math.log((1.0 + n) / (1.0 + df[t]))
               for t, c in Counter(toks).items() if df[t] >= min_df}
        norm = math.sqrt(sum(x * x for x in vec.values()))
        out[key] = {t: x / norm for t, x in vec.items()} if norm > 0 else {}
    return out


def cosine(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def keep_count(others: int) -> int:
    """Cuántos afines se guardan: el cuartil superior del grupo, entre ``MIN_KEEP`` y ``MAX_KEEP``."""
    return max(0, min(others, max(MIN_KEEP, min(MAX_KEEP, math.ceil(others / 4)))))


def affine_sets(docs: Mapping[Any, list[str]]) -> dict[Any, list[tuple[Any, float]]]:
    """Para cada documento, los más afines del corpus [(clave, coseno)] de mayor a menor (desempate por clave)."""
    vec = vectors(docs)
    keys = [k for k in docs if vec.get(k)]
    out: dict[Any, list[tuple[Any, float]]] = {}
    for k in keys:
        scored = sorted(((round(cosine(vec[k], vec[o]), 4), o) for o in keys if o != k),
                        key=lambda p: (-p[0], str(p[1])))
        out[k] = [(o, s) for s, o in scored[: keep_count(len(keys) - 1)] if s > 0]
    return out


def affine_from_tags(company: Any) -> dict[int, float]:
    """{CIK: coseno} de los afines guardados en la ficha."""
    out: dict[int, float] = {}
    for tag in getattr(company, "factor_tags", None) or []:
        text = str(tag).strip().lower()
        if not text.startswith(TAG_PREFIX):
            continue
        cik, _, score = text[len(TAG_PREFIX):].partition(":")
        try:
            out[int(cik)] = float(score)
        except ValueError:
            continue
    return out


def tag_affine(company: Any, pairs: Iterable[tuple[int, float]]) -> bool:
    """Sustituye las ``afin:`` de la ficha por ``pairs`` [(CIK, coseno)]. True si cambió."""
    old = list(getattr(company, "factor_tags", None) or [])
    keep = [t for t in old if not str(t).lower().startswith(TAG_PREFIX)]
    new = [*keep, *(f"{TAG_PREFIX}{int(cik)}:{score:.4f}" for cik, score in pairs)]
    if old == new:
        return False
    company.factor_tags = new
    return True


def latest_annual_url(cik: int, get_text: Callable[[str], str]) -> tuple[str, str, str] | None:
    """(url, formulario, fecha) del documento principal del último informe anual, o None."""
    data = json.loads(get_text(SUBMISSIONS.format(cik=str(int(cik)).zfill(10))))
    recent = (data.get("filings") or {}).get("recent") or {}
    for form, acc, doc, filed in zip(recent.get("form") or [], recent.get("accessionNumber") or [],
                                     recent.get("primaryDocument") or [], recent.get("filingDate") or [],
                                     strict=False):
        if form in ANNUAL_FORMS and doc:
            return ARCHIVE.format(cik=int(cik), acc=str(acc).replace("-", ""), doc=doc), form, filed
    return None


def describe(cik: int, name: str | None, get_text: Callable[[str], str]) -> dict[str, Any]:
    """{tokens, source, form, filed} o {missing: motivo}. Dos peticiones a la SEC."""
    found = latest_annual_url(cik, get_text)
    if found is None:
        return {"missing": "sin 10-K ni 20-F en la SEC"}
    url, form, filed = found
    text = plain_text(get_text(url))
    section, scope = business_section(text), "sección de negocio"
    if section is None:
        section, scope = text[:MAX_DOCUMENT_CHARS], "documento completo (sin encabezado de negocio)"
    if len(section) < MIN_SECTION_CHARS // 5:
        return {"missing": f"texto del {form} demasiado corto", "source": url}
    return {"tokens": tokens(section, drop=name_words(name)), "source": url, "form": form, "filed": filed,
            "scope": scope}


__all__ = ["MAX_KEEP", "MIN_KEEP", "RULE", "TAG_PREFIX", "affine_from_tags", "affine_sets", "business_section",
           "cosine", "describe", "keep_count", "latest_annual_url", "name_words", "plain_text", "tag_affine",
           "tokens", "vectors"]
