"""Enlace oficial al directo de un evento de resultados (registro IR verificado a mano).

Unica fuente: ``lib/ir-registry.ts`` (frontend). ``scripts/sync-ir-live-links.mjs``
extrae de ahi, por emisor y fecha de evento, el enlace al directo (``directo`` o, en
su defecto, ``webcast``) en ``app/data/ir_live_links.json``; el guard
``scripts/ir-live-links-guard.test.ts`` hace fallar la suite si el JSON se queda atras.

Reglas heredadas del registro: fecha exacta o nada; JSON ausente, invalido o con una
forma inesperada = sin enlace (fail-closed), nunca un enlace adivinado. Lo usa
``earnings_reminders`` para que el aviso del propio dia lleve el enlace al directo.
"""

from __future__ import annotations

import json
import logging
from functools import cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "ir_live_links.json"


@cache
def _links() -> dict[str, Any]:
    try:
        data = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        logger.warning("ir_live_links.json ilegible: los avisos salen sin enlace al directo", exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


def live_link_for(ticker: str, event_date: str) -> dict[str, str] | None:
    """``{kind, url, source}`` del directo oficial verificado, o None. Fecha exacta, nunca aproximada."""
    events = _links().get(str(ticker).upper())
    if not isinstance(events, dict):
        return None
    entry = events.get(str(event_date))
    if not isinstance(entry, dict):
        return None
    url = entry.get("url")
    kind = entry.get("kind")
    source = entry.get("source")
    if kind not in ("directo", "webcast"):
        return None
    if not (isinstance(url, str) and url.startswith("https://")):
        return None
    if not (isinstance(source, str) and source.startswith("https://")):
        return None
    return {"kind": kind, "url": url, "source": source}
