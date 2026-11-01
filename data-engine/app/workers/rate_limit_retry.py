"""Reintentos ante 429 que no acaban en dead-letter.

Medido en prod (lectura de dead-letter del 1-nov-2026): 82 lotes GDELT, 14
re-ingestas ESEF y 5 extracciones KPI acabaron en la cola XQ con un 429 de
la fuente. Todos eran refrescos con sustituto (el siguiente tick del
scheduler, o el backfill de KPI diferidos) y reencolaban con una espera fija
corta (GDELT: 60 s x 6 = 6 min), asi que la ventana del proveedor seguia
cerrada en cada intento y los reintentos se agotaban.

Politica comun:
- espera exponencial por intento (base * 2**reintentos, con techo) y jitter
  para que los workers que reciben el 429 a la vez no vuelvan juntos;
- el Retry-After del servidor manda siempre si es mayor (nunca se trunca);
- en el ULTIMO intento un 429 no se convierte en dead-letter: se registra y
  el mensaje se da por terminado (RateLimitRetriesExhausted), porque el
  siguiente ciclo programado repone el trabajo.
"""

from __future__ import annotations

import logging
import math
import random
from collections.abc import Callable

import dramatiq
from dramatiq.middleware import CurrentMessage

logger = logging.getLogger(__name__)

DEFAULT_JITTER_RATIO = 0.2


class RateLimitRetriesExhausted(Exception):
    """El ultimo intento tambien topo con el limite de la fuente.

    No es un fallo del trabajo: _handle_actor_error lo devuelve como
    resultado ``skipped`` (ack, sin dead-letter) y el siguiente ciclo lo
    cubre.
    """

    def __init__(self, source: str, retries: int, max_retries: int) -> None:
        super().__init__(
            f"{source}: limite de la fuente tras {retries} reintentos de {max_retries}; "
            "lote descartado, lo cubre el siguiente ciclo"
        )
        self.source = source
        self.retries = retries
        self.max_retries = max_retries


def retry_budget() -> tuple[int, int | None]:
    """(reintentos ya hechos, max_retries) del mensaje en ejecucion.

    Fuera de un worker (tests, llamada directa) devuelve (0, None): sin
    mensaje no hay presupuesto que agotar.
    """
    try:
        message = CurrentMessage.get_current_message()
    except Exception:  # noqa: BLE001 - sonda best-effort
        return 0, None
    if message is None:
        return 0, None
    options = getattr(message, "options", None) or {}
    try:
        retries = int(options.get("retries", 0) or 0)
    except (TypeError, ValueError):
        retries = 0
    max_retries = options.get("max_retries")
    if max_retries is None:
        actor_name = getattr(message, "actor_name", None)
        if actor_name:
            try:
                max_retries = dramatiq.get_broker().get_actor(actor_name).options.get("max_retries")
            except Exception:  # noqa: BLE001 - actor desconocido: sin presupuesto
                max_retries = None
    try:
        return retries, (int(max_retries) if max_retries is not None else None)
    except (TypeError, ValueError):
        return retries, None


def retries_exhausted() -> bool:
    """True si este es el ultimo intento: un fallo mas iria a dead-letter."""
    retries, max_retries = retry_budget()
    return max_retries is not None and retries >= max_retries


def backoff_seconds(
    retries: int,
    *,
    base: float,
    cap: float,
    retry_after: float | None = None,
    jitter_ratio: float = DEFAULT_JITTER_RATIO,
    rng: Callable[[], float] = random.random,
) -> float:
    """Espera antes del siguiente intento.

    - Primer intento (retries=0): la ventana del servidor si la da, si no
      ``base``.
    - Reintentos: crece a base * 2**retries hasta ``cap``.
    - La ventana del servidor nunca se acorta (aunque supere ``cap``).
    - Jitter multiplicativo en [0, jitter_ratio).
    """
    server = float(retry_after or 0.0)
    if not math.isfinite(server) or server < 0:
        server = 0.0
    first = server if server > 0 else float(base)
    grown = min(float(cap), float(base) * (2 ** min(max(retries, 0), 30))) if retries > 0 else 0.0
    wait = max(first, grown)
    return wait * (1.0 + max(0.0, jitter_ratio) * rng())


def retry_or_drop(
    source: str,
    *,
    base: float,
    cap: float,
    retry_after: float | None = None,
    jitter_ratio: float = DEFAULT_JITTER_RATIO,
) -> None:
    """Reencola con backoff, o descarta sin dead-letter si es el ultimo intento.

    Siempre lanza: ``dramatiq.Retry`` (con delay explicito) o
    ``RateLimitRetriesExhausted``.
    """
    retries, max_retries = retry_budget()
    if max_retries is not None and retries >= max_retries:
        logger.warning(
            "%s: 429 con los reintentos agotados (%s/%s); se descarta sin dead-letter, "
            "el siguiente ciclo lo cubre",
            source,
            retries,
            max_retries,
        )
        raise RateLimitRetriesExhausted(source, retries, max_retries)
    delay_s = backoff_seconds(retries, base=base, cap=cap, retry_after=retry_after, jitter_ratio=jitter_ratio)
    delay_ms = int(delay_s * 1000)
    raise dramatiq.Retry(
        f"{source}: limite de la fuente (429), reintento tras {delay_ms // 1000}s", delay=delay_ms
    )
