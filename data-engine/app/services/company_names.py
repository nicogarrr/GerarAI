"""Empresas nombradas por su nombre en una pregunta del Cerebro.

Revisión del worker de la biblioteca (2026-10-27): «¿Qué opina la carta de
Numantia sobre AST SpaceMobile?» y «¿Qué tengo apuntado sobre AST
SpaceMobile?» acababan en «No tengo «AST» entre las empresas de GerarAI»: la
primera palabra del nombre, en mayúsculas, se leía como un ticker que no
existe y la pregunta no llegaba ni a la ficha de ASTS ni a la biblioteca.

Aquí se reconoce el nombre de una empresa del maestro escrito en texto
llano:

- el nombre completo sin forma jurídica («AST SpaceMobile», «Brookfield
  Corporation»), en cualquier mayúscula/minúscula;
- o su primera palabra (≥ 4 letras) escrita con mayúscula inicial
  («Algoma», «Apple»), para no confundir palabras corrientes en minúscula.

Si el mismo texto encaja con varias empresas no se elige: el Cerebro
pregunta cuál.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache

from app.models.entities import Company

# Formas jurídicas y coletillas que no forman parte del nombre comercial.
_LEGAL_SUFFIXES = frozenset({
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "sa",
    "s.a", "sl", "ag", "nv", "se", "spa", "s.p.a", "ab", "asa", "oyj", "llc", "lp", "holdings",
    "holding", "group", "the", "class", "a", "b", "c", "adr", "ord", "shares",
})
# Primeras palabras demasiado genéricas para identificar una empresa solas.
_GENERIC_FIRST_WORDS = frozenset({
    "grupo", "group", "banco", "bank", "first", "american", "general", "international", "global",
    "united", "national", "new", "china", "the", "royal", "compania", "company", "pool", "block",
    "target", "meta", "visa", "booking", "match", "service", "energy", "capital", "health",
})


# Primeras palabras genéricas tras las que va el nombre propio («Banco
# Santander»). Solo sin conector: «Banco de Sabadell» no entra («de»).
_PREFIX_FIRST_WORDS = frozenset({"banco", "grupo"})


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn"
    ).lower()


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9&]+", _fold(text))


# Match dotted legal forms as a unit, only at the end. Never discard lone
# "s"/"l" tokens: they may be part of a real commercial name.
_DOTTED_LEGAL_END = re.compile(
    r"(?<![a-z0-9&])(?:s\.\s*[al]|s\.\s*p\.\s*a|n\.\s*v|l\.\s*l\.\s*c|l\.\s*p)\.?[\s,;]*$"
)


@lru_cache(maxsize=8192)
def _core_words(name: str) -> tuple[str, ...]:
    # Only immutable text is retained, not ORM objects, ids or tenant state.
    # The key is the current name, so renaming a company needs no invalidation.
    folded = _fold(name).rstrip(" ,;.")
    while True:
        stripped = _DOTTED_LEGAL_END.sub("", folded).rstrip(" ,;.")
        if stripped != folded:
            folded = stripped
            continue
        words = _words(stripped)
        if words and words[-1] in _LEGAL_SUFFIXES:
            # Remove the terminal token in the source, then reconsider dotted
            # suffixes (e.g. "Banco Santander S.A. ADR").
            token = list(re.finditer(r"[a-z0-9&]+", stripped))[-1]
            folded = stripped[:token.start()].rstrip(" ,;.")
            continue
        return tuple(words)


def core_name(name: str) -> list[str]:
    """Palabras del nombre comercial sin la forma jurídica final."""
    return list(_core_words(name))


@dataclass
class NameMatches:
    """Empresas nombradas y los tramos de texto que ocupan sus nombres."""

    companies: list[Company] = field(default_factory=list)
    #: Primera palabra que encaja con varias empresas: (palabra, empresas).
    ambiguous: list[tuple[str, list[Company]]] = field(default_factory=list)
    spans: list[tuple[int, int]] = field(default_factory=list)

    def covers(self, start: int, end: int) -> bool:
        return any(s <= start and end <= e for s, e in self.spans)


def _phrase_re(words: list[str] | tuple[str, ...]) -> re.Pattern[str]:
    return _cached_phrase_re(tuple(words))


@lru_cache(maxsize=4096)
def _cached_phrase_re(words: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])" + r"[\s\-.,]+".join(re.escape(w) for w in words) + r"(?![a-z0-9])")


def companies_named_in(question: str, companies: Iterable[Company]) -> NameMatches:
    """Empresas del maestro nombradas por su nombre en ``question``."""
    text = question or ""
    folded = _fold(text)  # mismas posiciones que ``text`` salvo letras combinadas
    if len(folded) != len(text):
        folded = "".join(_fold(ch) or " " for ch in text)
    out = NameMatches()
    by_first: dict[str, list[Company]] = {}
    seen: set[int] = set()
    for company in companies:
        words = _core_words(company.name or "")
        if words and words[0] == "the" and len(words) >= 2:
            words = words[1:]  # «The Coca-Cola Company» → «coca cola»
        if not words:
            continue
        if len(words) >= 2 and len(compact := "".join(words)) >= 6 and compact in folded:
            # Nombre de varias palabras escrito junto («cocacola»), en cualquier caja.
            for m in _phrase_re([compact]).finditer(folded):
                if company.id not in seen:
                    seen.add(company.id)
                    out.companies.append(company)
                out.spans.append((m.start(), m.end()))
        # A literal substring is a necessary (not sufficient) condition of
        # this regex. Avoid compiling/searching patterns that cannot match.
        # Unlike token-set filtering this also preserves names containing '&'.
        if len(words) >= 2 and all(word in folded for word in words):
            for m in _phrase_re(words).finditer(folded):
                if company.id not in seen:
                    seen.add(company.id)
                    out.companies.append(company)
                out.spans.append((m.start(), m.end()))
        first = next(iter(words))
        if first in _PREFIX_FIRST_WORDS and len(words) >= 2:
            # «Banco Santander», «Grupo Ezentis»: se nombran por la segunda
            # palabra («¿vendo Santander?»), con mayúscula como la primera.
            first = words[1]
        if len(first) >= 4 and first not in _GENERIC_FIRST_WORDS and first in folded:
            by_first.setdefault(first, []).append(company)
    for first, candidates in by_first.items():
        for m in _phrase_re([first]).finditer(folded):
            raw = text[m.start():m.end()]
            if not raw[:1].isupper():
                continue  # en minúscula es una palabra corriente («apple» no, «Apple» sí)
            if any(s <= m.start() < e for s, e in out.spans):
                continue  # ya cubierto por un nombre completo
            fresh = [c for c in candidates if c.id not in seen]
            if len(candidates) == 1:
                if fresh:
                    seen.add(fresh[0].id)
                    out.companies.append(fresh[0])
                out.spans.append((m.start(), m.end()))
            elif not any(c.id in seen for c in candidates):
                out.ambiguous.append((raw, candidates))
                out.spans.append((m.start(), m.end()))
    return out


def ambiguous_name_answer(word: str, candidates: list[Company]) -> str:
    options = " o ".join(f"{c.ticker} ({c.name})" for c in candidates[:4])
    return f"«{word}» puede ser varias empresas de GerarAI: ¿te refieres a {options}?"


def _osa_distance(a: str, b: str, limit: int) -> int:
    """Distancia de edición con transposición de dos letras vecinas (OSA), cortada en ``limit + 1``."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


def company_misspelled_in(
    question: str, companies: Iterable[Company], *, skip_words: frozenset[str] = frozenset()
) -> Company | None:
    """Empresa escrita con una errata («micrsoft», «Mircosoft», «microsfot»).

    Prueba real 2026-11-03: «micrsoft esta cara?» no se reconocía y la
    respuesta era genérica, sin tus datos. Solo palabras de ≥ 5 letras contra
    nombres de ≥ 5 letras no genéricos; una letra de diferencia (o dos
    vecinas cambiadas) hasta 7 letras, dos desde 8; en minúsculas también
    vale el nombre exacto. Si encaja con más de una empresa no se elige.
    Quien llama decide sobre qué empresas buscar (las del usuario) y exige
    una pista de consulta de inversión.
    """
    names: dict[str, set[int]] = {}
    by_id: dict[int, Company] = {}
    for company in companies:
        words = _core_words(company.name or "")
        if words and words[0] == "the" and len(words) >= 2:
            words = words[1:]
        if not words:
            continue
        keys = {words[0]}
        if len(words) >= 2:
            keys.add("".join(words))
        for key in keys:
            if len(key) >= 5 and key not in _GENERIC_FIRST_WORDS and key.isalpha():
                names.setdefault(key, set()).add(company.id)
                by_id[company.id] = company
    if not names:
        return None
    found: set[int] = set()
    for token in set(_words(question)):
        if len(token) < 5 or not token.isalpha() or token in skip_words:
            continue
        limit = 1 if len(token) <= 7 else 2
        for key, ids in names.items():
            if _osa_distance(token, key, limit) <= limit:
                found |= ids
    if len(found) != 1:
        return None
    return by_id[next(iter(found))]
