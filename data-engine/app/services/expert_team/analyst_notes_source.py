"""Notas de analista (#4582) como evidencia del equipo de expertos.

Costura entre la tabla ``analyst_notes`` y las etapas que leen argumentos de
analistas: la mezcla de analistas (``run_analyst_blend(extra_sources=…)``) y el
escéptico (``run_esceptico(extra_sources=…)``). Solo entran notas
``verificado`` (cita encontrada en la fuente): un fragmento de agregador no
trae cita y un post en redes es rumor, y ninguna de las dos cosas puede
sostener un supuesto. Por tenant y ticker; nada por empresa concreta.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.analyst_note import AnalystNote
from app.services.expert_team.models import RunContext, ToolOutput

#: Antigüedad máxima de una nota para contar como argumento vigente.
NOTE_MAX_AGE_DAYS = 365
#: Notas por firma (la más reciente primero).
NOTES_PER_FIRM = 1
#: Sin lista de firmas: cuántas notas recientes se leen.
RECENT_NOTES_LIMIT = 20
QUOTE_CHARS = 1500


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def note_output(note: AnalystNote) -> ToolOutput:
    """Una nota como salida citable: la cita literal va en ``text``."""
    data: dict[str, Any] = {
        "firm": note.firm,
        "analyst": note.analyst,
        "action": note.action,
        "rating": note.rating_new,
        "price_target": _jsonable(note.pt_new),
        "currency": note.currency,
        "text": (note.quote or "")[:QUOTE_CHARS],
        "key_arguments": list(note.key_arguments or []),
        "estimates": _jsonable(note.estimates or {}),
        "valuation": _jsonable(note.valuation or {}),
        "segment_assumptions": _jsonable(note.segment_assumptions or {}),
        "bull_case": note.bull_case,
        "bear_case": note.bear_case,
        "catalysts": list(note.catalysts or []),
        "risks": list(note.risks or []),
    }
    return ToolOutput(
        source={
            "table": "analyst_notes",
            "id": str(note.id),
            "firm": note.firm,
            "url": note.source_url or "",
            "date": note.note_date.isoformat() if note.note_date else "",
        },
        data={k: v for k, v in data.items() if v not in (None, "", [], {})},
    )


def analyst_notes_source(
    db: Session, *, today: date | None = None, max_age_days: int = NOTE_MAX_AGE_DAYS
) -> Callable[[RunContext, Sequence[str]], list[ToolOutput]]:
    """Fuente extra: las notas verificadas más recientes de las firmas dadas (o del ticker)."""
    from app.services.analyst_note_service import analyst_note_service

    def source(ctx: RunContext, firms: Sequence[str]) -> list[ToolOutput]:
        if type(ctx.tenant_id) is not int or not ctx.ticker:
            return []
        if firms:
            notes = analyst_note_service.latest_by_firm(
                db, ctx.tenant_id, ctx.ticker, list(firms), per_firm=NOTES_PER_FIRM
            )
        else:
            notes = analyst_note_service.list_notes(db, ctx.tenant_id, ctx.ticker, limit=RECENT_NOTES_LIMIT)
        since = (today or date.today()) - timedelta(days=max_age_days)
        return [
            note_output(n)
            for n in notes
            if n.verification == "verificado" and (n.quote or "").strip() and n.note_date >= since
        ]

    return source


__all__ = ["NOTE_MAX_AGE_DAYS", "analyst_notes_source", "note_output"]
