"""Calendario macro (FOMC + BLS) con fuente y fecha en cada evento.

Solo publicaciones de alto impacto: reuniones FOMC, IPC, empleo, IPP, JOLTS e
indice de costes laborales. Cada fuente degrada por separado (``partial``).
Cache en memoria de 6 h: los calendarios oficiales cambian muy pocas veces.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, date, datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.connectors import macro_calendar as connector

CACHE_TTL_SECONDS = 6 * 3600
MAX_RANGE_DAYS = 366

# titulo BLS -> (clave, titulo en español)
BLS_RELEASES: dict[str, tuple[str, str]] = {
    "Consumer Price Index": ("cpi", "IPC de EE. UU. (inflación)"),
    "Employment Situation": ("employment", "Informe de empleo de EE. UU."),
    "Producer Price Index": ("ppi", "IPP de EE. UU. (precios al productor)"),
    "Job Openings and Labor Turnover Survey": ("jolts", "JOLTS: ofertas de empleo"),
    "Employment Cost Index": ("eci", "Índice de costes laborales"),
}

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def clear_cache() -> None:
    _cache.clear()


async def _cached(key: str, loader, *, use_cache: bool) -> list[dict[str, Any]]:
    now = time.monotonic()
    hit = _cache.get(key)
    if use_cache and hit and now - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    value = await loader()
    if use_cache:
        _cache[key] = (now, value)
    return value


def _fomc_event(raw: dict[str, Any]) -> dict[str, Any]:
    title = "Reunión del FOMC (decisión de tipos)"
    return {
        "kind": "fomc",
        "date": raw["date"],
        "start_date": raw["start_date"],
        "time_et": None,
        "title": title,
        "detail": "Con proyecciones económicas" if raw["projections"] else None,
        "source": "Reserva Federal",
        "source_url": connector.FOMC_URL,
        "label": "OFICIAL",
    }


def _bls_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    release = BLS_RELEASES.get(raw["title"])
    if release is None:
        return None
    kind, title = release
    return {
        "kind": kind,
        "date": raw["date"],
        "start_date": raw["date"],
        "time_et": raw["time_et"],
        "title": title,
        "detail": None,
        "source": "BLS",
        "source_url": connector.BLS_SCHEDULE_URL,
        "label": "OFICIAL",
    }


async def get_macro_events(
    start: date,
    end: date,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Eventos entre ``start`` y ``end`` (ambos incluidos), ordenados por fecha."""
    if start > end:
        raise ValueError("desde no puede ser posterior a hasta")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(f"rango máximo: {MAX_RANGE_DAYS} días")
    agent = get_settings().sec_user_agent
    use_cache = client is None
    sources: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    fetched_at = datetime.now(UTC).isoformat()

    async def run(name: str, url: str, loader, convert) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        try:
            rows = await _cached(name, loader, use_cache=use_cache)
        except (httpx.HTTPError, ValueError):
            return (
                {"name": name, "url": url, "status": "unavailable", "fetched_at": fetched_at,
                 "covered_until": None},
                [],
            )
        converted = [item for item in (convert(row) for row in rows) if item is not None]
        # Una fuente que responde pero ya no tiene eventos (formato cambiado)
        # no es "sin eventos": es no disponible.
        status = "ready" if converted else "unavailable"
        covered_until = max((row["date"] for row in rows), default=None)
        # El calendario oficial solo llega hasta covered_until: si el rango pedido
        # lo supera, no se puede afirmar que no haya mas eventos de esa fuente.
        if status == "ready" and covered_until is not None and end.isoformat() > covered_until:
            status = "partial"
        return (
            {"name": name, "url": url, "status": status, "fetched_at": fetched_at,
             "covered_until": covered_until},
            converted,
        )

    # Las dos fuentes en PARALELO (antes en serie: 479 ms medidos en el
    # barrido 2026-10-31 con cache fria por worker). El orden del contrato
    # (FOMC primero, BLS segundo) se conserva al ensamblar, no por llegada.
    results = await asyncio.gather(
        run("Reserva Federal (FOMC)", connector.FOMC_URL,
            lambda: connector.fetch_fomc(agent, client), _fomc_event),
        run("BLS", connector.BLS_SCHEDULE_URL,
            lambda: connector.fetch_bls(agent, client), _bls_event),
    )
    for source, converted in results:
        sources.append(source)
        events.extend(converted)

    low, high = start.isoformat(), end.isoformat()
    inside = sorted(
        (e for e in events if low <= e["date"] <= high),
        key=lambda e: (e["date"], e["time_et"] or "", e["kind"]),
    )
    usable = [s for s in sources if s["status"] != "unavailable"]
    status = ("ready" if all(s["status"] == "ready" for s in sources)
              else ("partial" if usable else "unavailable"))
    return {"status": status, "from": low, "to": high, "total": len(inside),
            "events": inside, "sources": sources}
