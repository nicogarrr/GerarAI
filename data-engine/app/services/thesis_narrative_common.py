"""Utilidades compartidas por las narrativas de tesis (deep y news)."""

from __future__ import annotations

from app.core.config import get_settings


def narrative_reasoning_effort(section: str, explicit: str | None) -> str | None:
    """Valor explicito del env si existe; si no, la tabla por seccion."""
    if explicit is not None and explicit.strip():
        return explicit.strip()
    return get_settings().reasoning_effort_for(section)
