"""Seccion de razonamiento de una pregunta de Cerebro (consulta vs. cartera).

La tabla de esfuerzos vive en ``app.core.config.LLM_REASONING_EFFORT_DEFAULTS``
y se sobreescribe con ``LLM_REASONING_EFFORT_BY_SECTION``. Este modulo solo
decide a que seccion pertenece una pregunta del chat con datos.
"""

from __future__ import annotations

import re

from app.core.config import Settings, get_settings

#: Analisis de la cartera completa: posiciones propias, diversificacion,
#: concentracion, riesgos o comparativas entre posiciones.
_PORTFOLIO_RE = re.compile(
    r"(?i)\b(?:mi|mis|nuestra)\s+(?:cartera|posici[oó]n(?:es)?|inversi[oó]n(?:es)?|acciones|holdings)\b"
    r"|\b(?:my|our)\s+(?:portfolio|positions|holdings)\b"
    r"|\bcartera\b|\bportfolio\b|\bwatchlist\b|\bseguimiento\b"
    r"|\bdiversific\w*|\bconcentraci[oó]n\b|\brebalance\w*|\breequilibr\w*"
)


def chat_section_for(question: str | None) -> str:
    """``chat_cartera`` si la pregunta analiza la cartera; si no, ``chat_consulta``."""
    return "chat_cartera" if _PORTFOLIO_RE.search(question or "") else "chat_consulta"


def chat_reasoning_effort(question: str | None, settings: Settings | None = None) -> str | None:
    """Esfuerzo de razonamiento de una pregunta de Cerebro con datos."""
    return (settings or get_settings()).reasoning_effort_for(chat_section_for(question))
