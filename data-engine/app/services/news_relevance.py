"""Relevancia de una noticia para una empresa: criterio medible.

La empresa debe aparecer en el titular, o mencionarse al menos `MIN_BODY_MENTIONS`
veces en el texto. Una noticia que solo la nombra de pasada (p. ej. un articulo sobre
Tieto que cita a Microsoft una vez) no abre revision de tesis ni alerta "material".
"""

from __future__ import annotations

import re

_NAME_NOISE = {"inc", "corp", "corporation", "company", "co", "holdings", "holding", "group",
               "limited", "ltd", "plc", "the", "sa", "ag", "nv", "class", "common", "stock"}
MIN_BODY_MENTIONS = 3


def _company_terms(ticker: str | None, name: str | None) -> list[str]:
    terms = [(ticker or "").upper()]
    terms += [w for w in re.split(r"\W+", name or "") if len(w) >= 4 and w.lower() not in _NAME_NOISE]
    return [t for t in terms if t]


def _count_mentions(terms: list[str], text: str) -> int:
    return sum(len(re.findall(rf"(?<!\w){re.escape(t)}(?!\w)", text, flags=re.IGNORECASE)) for t in terms)


def company_is_central(
    ticker: str | None, name: str | None, *, headline: str | None, text: str,
    min_mentions: int = MIN_BODY_MENTIONS,
) -> bool:
    """True si la empresa esta en el titular o se menciona >= `min_mentions` veces.

    El prefijo con el ticker que anade el feed no cuenta como evidencia.
    """
    terms = _company_terms(ticker, name)
    if not terms:
        return False
    tk = re.escape((ticker or "").upper())

    def _strip(value: str) -> str:
        return re.sub(rf"^\s*\$?{tk}\b[\s:\-]*", "", value or "", flags=re.IGNORECASE) if tk else (value or "")

    head = _strip(headline or "")
    if head and _count_mentions(terms, head) > 0:
        return True
    return _count_mentions(terms, _strip(text)) >= min_mentions
