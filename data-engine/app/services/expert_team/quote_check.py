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


def is_literal(quote: str, folded_evidence: Sequence[str]) -> bool:
    """La cita está tal cual en alguna evidencia; una elipsis («…» o «...») la parte en trozos literales."""
    q = fold(quote).replace("...", "…").strip(" .…")
    if not q:
        return True
    pieces = [p.strip(" .,;") for p in q.split("…") if p.strip(" .,;")]
    return all(any(piece in e for e in folded_evidence) for piece in pieces)


def _same(text: str) -> str:
    return text


def non_literal(text: str, evidence: Iterable[str], render: Callable[[str], str] = _same) -> list[str]:
    """Citas que no están literales; ``render`` sustituye los marcadores antes de comparar."""
    folded = [fold(e) for e in evidence]
    return [render(q) for _s, _e, q in quotes(text) if not is_literal(render(q), folded)]


def unquote_non_literal(text: str, evidence: Iterable[str],
                        render: Callable[[str], str] = _same) -> tuple[str, list[str]]:
    """Último recurso: la cita que no está en la evidencia deja de ir entre comillas (ya no se presenta
    como palabras del documento). Devuelve el texto y las citas tocadas."""
    folded = [fold(e) for e in evidence]
    touched: list[str] = []
    pieces, last = [], 0
    for start, end, q in quotes(text):
        if is_literal(render(q), folded):
            continue
        pieces.append(text[last:start])
        pieces.append(q)
        last = end
        touched.append(render(q))
    pieces.append(text[last:])
    return "".join(pieces), touched


__all__ = ["QUOTE", "evidence_texts", "fold", "is_literal", "non_literal", "quotes", "unquote_non_literal"]
