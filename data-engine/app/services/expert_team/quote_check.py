"""Citas literales: lo que va entre comillas tiene que estar tal cual en la evidencia citada.

Medido el 8-nov-2026 sobre 22 tesis v2: 15 de 37 citas atribuidas no aparecían literales en los documentos y
11 eran traducciones al español presentadas como cita. Regla: la cita va en el idioma original del documento,
tal cual, y la traducción al lado marcada como traducción: «original» (traducción: …). Una cita que no está en
la evidencia se rechaza; si tras los reintentos sigue sin estar, deja de presentarse como cita (se quitan las
comillas) y queda registrada.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: Entre comillas angulares, inglesas o rectas; las de menos de 25 caracteres son énfasis, no citas.
QUOTE = re.compile(r"[«“\"]([^«»“”\"]{25,800})[»”\"]")
#: La traducción va marcada justo antes: «(traducción: «…»)», «trad.:», «en español:».
_TRANSLATION = re.compile(r"(?:traducci[oó]n|trad\.|en espa[nñ]ol)\s*:?\s*$", re.I)


def fold(text: str) -> str:
    """Comparable: sin mayúsculas, acentos, comillas tipográficas ni espacios repetidos."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).casefold()
    t = t.replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-").replace("\u00a0", " ")
    t = re.sub(r"[«»“”\"]", "", t)
    return " ".join(t.split())


def evidence_texts(*blocks: Any) -> list[str]:
    """Todas las cadenas de la evidencia (pasajes, guía, analistas…), recorridas en profundidad."""
    out: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            if len(value) >= 25:
                out.append(value)
        elif isinstance(value, Mapping):
            for item in value.values():
                walk(item)
        elif isinstance(value, list | tuple):
            for item in value:
                walk(item)

    for block in blocks:
        walk(block)
    return out


def quotes(text: str) -> list[tuple[int, int, str]]:
    """Citas del texto (inicio, fin, contenido), sin contar las traducciones marcadas."""
    out = []
    for m in QUOTE.finditer(text or ""):
        before = (text or "")[max(0, m.start() - 24):m.start()]
        if _TRANSLATION.search(before.rstrip(" (")):
            continue
        if m.group(1).lstrip().startswith(("¿", "¡")):
            continue  # pregunta o exclamación retórica del propio texto («¿qué tiene que ocurrir…?»), no una cita
        out.append((m.start(), m.end(), m.group(1)))
    return out


#: Tipos de documento por los que la prosa atribuye una cita («según el 10-K», «el informe anual dice»). Cada tipo
#: lleva el patrón con el que se reconoce en el TÍTULO del documento y el patrón con el que se nombra en la PROSA
#: (los dos sobre texto ``fold``). Un 10-K o un 20-F también es «el informe anual».
DOC_KINDS: dict[str, tuple[str, str]] = {
    "10-k": (r"\b10-?k\b", r"\b10-?k\b"),
    "10-q": (r"\b10-?q\b", r"\b10-?q\b"),
    "20-f": (r"\b20-?f\b", r"\b20-?f\b"),
    "40-f": (r"\b40-?f\b", r"\b40-?f\b"),
    "8-k": (r"\b8-?k\b", r"\b8-?k\b"),
    "6-k": (r"\b6-?k\b", r"\b6-?k\b"),
    "proxy": (r"\bdef ?14a\b|\bproxy\b", r"\bdef ?14a\b|\bproxy\b"),
    "informe anual": (r"annual report|informe anual|memoria anual|annual accounts|cuentas anuales|universal registration"
                      r"|document d'enregistrement|\b10-?k\b|\b20-?f\b|\b40-?f\b",
                      r"informe anual|memoria anual|annual report|cuentas anuales|documento de registro"),
    "informe trimestral": (r"\b10-?q\b|quarterly report|interim report|half[- ]year|informe (?:trimestral|semestral)"
                           r"|\bq[1-4]\b", r"informe (?:trimestral|semestral|intermedio)|quarterly report"),
    "resultados": (r"earnings|results|resultados|press release|\b8-?k\b|\b6-?k\b",
                   r"nota de (?:resultados|prensa)|comunicado de resultados|press release|earnings release"),
    "presentacion": (r"presentation|presentaci[o]n|investor day|slides", r"presentacion|investor day"),
    "conferencia": (r"transcript|earnings call|conference call|conferencia", r"conferencia (?:de|con) (?:resultados|analistas)"
                    r"|earnings call|conference call"),
    "carta": (r"letter|carta", r"carta (?:a|de)l? (?:los )?accionistas|shareholder letter|carta anual"),
}
#: Bloques de evidencia que no son documentos: cómo los nombra la prosa.
BLOCK_ALIASES: dict[str, tuple[str, ...]] = {
    "guidance": ("guia de la empresa", "guidance", "previsiones de la empresa"),
    "analysts": ("analistas", "consenso"),
    "price_targets": ("analistas", "precio objetivo", "precios objetivo"),
    "insiders": ("form 4", "formulario 4", "insiders"),
    "experts": ("equipo de expertos", "investigador", "esceptico"),
}
#: Hasta dónde se mira alrededor de la cita para leer a qué documento se atribuye.
ATTRIBUTION_BEFORE, ATTRIBUTION_AFTER = 220, 100


@dataclass(frozen=True)
class Source:
    """Un documento de la evidencia: nombre, textos ``fold`` (cada pasaje por separado) y los tipos por los
    que la prosa lo puede nombrar."""

    name: str
    texts: tuple[str, ...]
    kinds: frozenset[str] = frozenset()


def _title_kinds(title: str) -> frozenset[str]:
    t = fold(title)
    kinds = {k for k, (in_title, _prose) in DOC_KINDS.items() if re.search(in_title, t)}
    if t:
        kinds.add("titulo:" + t)
    return frozenset(kinds)


def evidence_sources(passages: Iterable[Mapping[str, Any]] = (), **blocks: Any) -> list[Source]:
    """La evidencia separada por documento (no aplanada): cada documento de ``passages`` es una fuente con sus
    pasajes; cada bloque con nombre (``guidance=…``, ``analysts=…``) es otra fuente con sus cadenas."""
    by_doc: dict[tuple[str, str], list[str]] = {}
    for p in passages or ():
        if not isinstance(p, Mapping) or not isinstance(p.get("text"), str):
            continue
        key = (str(p.get("document") or ""), str(p.get("url") or ""))
        by_doc.setdefault(key, []).append(fold(p["text"]))
    out = [Source(name=title or url or "documento sin título", texts=tuple(texts), kinds=_title_kinds(title))
           for (title, url), texts in by_doc.items()]
    for name, block in blocks.items():
        texts = tuple(fold(t) for t in evidence_texts(block))
        if texts:
            aliases = BLOCK_ALIASES.get(name, ())
            out.append(Source(name=name, texts=texts, kinds=frozenset("alias:" + a for a in aliases)))
    return out


def _as_sources(evidence: Iterable[Source | str]) -> list[Source]:
    """Una cadena suelta es un documento anónimo (no se le puede atribuir nada por nombre)."""
    return [e if isinstance(e, Source) else Source(name="", texts=(fold(e),)) for e in evidence]


def attributed_kinds(context: str) -> frozenset[str]:
    """Tipos de documento que la prosa nombra alrededor de la cita (texto ``fold``)."""
    c = fold(context)
    kinds = {k for k, (_title, in_prose) in DOC_KINDS.items() if re.search(in_prose, c)}
    kinds |= {"alias:" + a for aliases in BLOCK_ALIASES.values() for a in aliases if a in c}
    return frozenset(kinds)


def _pieces(quote: str) -> list[str]:
    q = fold(quote).replace("...", "…").strip(" .…")
    return [p.strip(" .,;") for p in q.split("…") if p.strip(" .,;")]


def _in_order(pieces: Sequence[str], text: str) -> bool:
    """Todos los trozos en ``text``, en el orden de la cita y sin solaparse (el más a la izquierda que cabe)."""
    pos = 0
    for piece in pieces:
        at = text.find(piece, pos)
        if at < 0:
            return False
        pos = at + len(piece)
    return True


def _in_source(pieces: Sequence[str], source: Source) -> bool:
    """La cita entera sale de UN pasaje de este documento, en orden y sin solapes."""
    return any(_in_order(pieces, t) for t in source.texts)


def _named(source: Source, kinds: frozenset[str], context: str) -> bool:
    titles = {k[len("titulo:"):] for k in source.kinds if k.startswith("titulo:")}
    return bool(source.kinds & kinds) or any(len(t) >= 4 and t in fold(context) for t in titles)


def literal_problem(quote: str, evidence: Iterable[Source | str], context: str = "") -> str | None:
    """Por qué la cita no está tal cual en el documento citado, o ``None`` si lo está.

    - Cada trozo (una elipsis «…» o «...» la parte) tiene que estar en UN solo documento, en el orden de la cita
      y sin solaparse: no se aceptan trozos de documentos distintos ni en orden invertido.
    - Si la prosa de alrededor (``context``) nombra el documento («según el 10-K»), se busca solo en ese; si
      el documento nombrado no está en la evidencia, la cita se rechaza.
    """
    pieces = _pieces(quote)
    if not pieces:
        return None
    sources = _as_sources(evidence)
    kinds = attributed_kinds(context)
    named = [s for s in sources if _named(s, kinds, context)]
    if kinds and not named:
        return "el documento al que se atribuye no está en la evidencia"
    cited = named or sources
    if any(_in_source(pieces, s) for s in cited):
        return None
    if len(pieces) > 1:
        if all(any(any(p in t for t in s.texts) for s in cited) for p in pieces):
            if not any(all(any(p in t for t in s.texts) for p in pieces) for s in cited):
                return "junta trozos de documentos distintos"
            return "los trozos no están en el orden del documento o se solapan"
    return "no está literal en el documento citado"


def is_literal(quote: str, evidence: Iterable[Source | str], context: str = "") -> bool:
    """La cita está tal cual en el documento citado (ver ``literal_problem``)."""
    return literal_problem(quote, evidence, context) is None


def _same(text: str) -> str:
    return text


def _context(text: str, start: int, end: int) -> str:
    """La prosa de la frase de la cita: hacia atrás hasta la cita anterior o el punto, y un poco detrás."""
    before = text[max(0, start - ATTRIBUTION_BEFORE):start]
    cut = max(before.rfind(". "), before.rfind("»"), before.rfind("”"), before.rfind("\n"))
    before = before[cut + 1:] if cut >= 0 else before
    after = text[end:end + ATTRIBUTION_AFTER]
    stop = min([i for i in (after.find(". "), after.find("«"), after.find("“"), after.find("\n")) if i >= 0] or [len(after)])
    after = after[:stop]
    # «(traducción: «…»)» detrás de la cita no es atribución.
    after = re.sub(r"\(\s*(?:traducci[oó]n|trad\.|en espa[nñ]ol)[^)]*\)?", " ", after, flags=re.I)
    return before + " " + after


def literal_problems(text: str, evidence: Iterable[Source | str],
                     render: Callable[[str], str] = _same) -> list[tuple[str, str]]:
    """(cita, motivo) de cada cita que no está tal cual en su documento; ``render`` sustituye los marcadores."""
    sources = _as_sources(evidence)
    out = []
    for start, end, q in quotes(text):
        why = literal_problem(render(q), sources, render(_context(text, start, end)))
        if why:
            out.append((render(q), why))
    return out


def non_literal(text: str, evidence: Iterable[Source | str], render: Callable[[str], str] = _same) -> list[str]:
    """Citas que no están literales en el documento citado."""
    return [q for q, _why in literal_problems(text, evidence, render)]


def unquote_non_literal(text: str, evidence: Iterable[Source | str],
                        render: Callable[[str], str] = _same) -> tuple[str, list[str]]:
    """Último recurso: la cita que no está en la evidencia deja de ir entre comillas (ya no se presenta
    como palabras del documento). Devuelve el texto y las citas tocadas."""
    sources = _as_sources(evidence)
    touched: list[str] = []
    pieces, last = [], 0
    for start, end, q in quotes(text):
        if literal_problem(render(q), sources, render(_context(text, start, end))) is None:
            continue
        pieces.append(text[last:start])
        pieces.append(q)
        last = end
        touched.append(render(q))
    pieces.append(text[last:])
    return "".join(pieces), touched


__all__ = ["QUOTE", "Source", "attributed_kinds", "evidence_sources", "evidence_texts", "fold", "is_literal",
           "literal_problem", "literal_problems", "non_literal", "quotes", "unquote_non_literal"]
