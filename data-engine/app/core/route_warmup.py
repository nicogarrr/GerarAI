"""Precalentado de las rutas de FastAPI al arrancar.

FastAPI 0.14x construye el contexto efectivo de cada ruta (dependencias,
modelos de pydantic de cada parametro) de forma perezosa, la primera vez que
una peticion recorre su router incluido. Con ~190 rutas, las primeras
peticiones tras un arranque (deploy, o Render despertando el servicio) pagaban
ese coste: medido en local, /api/companies/{t}/events 416 ms y
/api/companies/{t}/thesis-5y 695 ms la primera vez frente a 10 y 45 ms despues.

``warm_route_contexts`` recorre los routers incluidos y fuerza esa
construccion una vez, en un hilo de fondo, para que ninguna peticion la pague.
Es la misma construccion que haria la primera peticion (mismo lock y misma
cache de FastAPI), solo que antes. Es best-effort: si una version futura de
FastAPI cambia esta API interna, no hace nada y no rompe el arranque.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


def warm_route_contexts(app: Any) -> int:
    """Construye los contextos de todas las rutas incluidas. Devuelve cuantos routers."""
    warmed = 0
    stack = list(getattr(getattr(app, "router", None), "routes", []) or [])
    while stack:
        route = stack.pop()
        candidates = getattr(route, "effective_candidates", None)
        if not callable(candidates):
            continue
        try:
            children = candidates()
            low_priority = getattr(route, "effective_low_priority_routes", None)
            if callable(low_priority):
                low_priority()
        except Exception:  # pragma: no cover - best effort ante cambios de FastAPI
            logger.debug("No se pudo precalentar un router", exc_info=True)
            continue
        warmed += 1
        stack.extend(children)
    return warmed


def start_route_warmup(app: Any) -> threading.Thread:
    """Lanza el precalentado en un hilo daemon (no retrasa el arranque)."""

    def _run() -> None:
        started = time.perf_counter()
        try:
            warmed = warm_route_contexts(app)
        except Exception:  # pragma: no cover - nunca debe tumbar el proceso
            logger.warning("Precalentado de rutas fallido", exc_info=True)
            return
        logger.info(
            "Rutas precalentadas: %s routers en %.0f ms",
            warmed,
            (time.perf_counter() - started) * 1000,
        )

    thread = threading.Thread(target=_run, name="gerarai-route-warmup", daemon=True)
    thread.start()
    return thread
