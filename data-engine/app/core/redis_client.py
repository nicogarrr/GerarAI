"""Helper compartido de cliente Redis perezoso con backoff.

core/cache.py y services/movers_cache.py llevaban la misma conexion copiada:
estado por modulo ``{"client": None, "down_until": 0.0}``, backoff de 30 s
tras un fallo, timeouts cortos y ``retry=no_retry()`` (ver redis_retry.py).
Aqui vive una sola copia; cada modulo conserva SU estado (sus circuitos son
independientes a proposito) y sus parametros (timeouts, ping inicial, log).

``short_async_redis`` es la variante async y de vida corta para las guardas
(rate-limit, nonce anti-replay): un cliente por comprobacion, timeouts de
1.0/1.5 s (la contencion de CPU del arranque en frio puede superar los
250/500 ms), ``retry=no_retry_async()`` (no reintentar una escritura
ambiguamente confirmada) y cierre siempre; el fallo lo gestiona el caller
(fail closed o degradado local).
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

REDIS_BACKOFF_S = 30.0


def redis_down(state: dict[str, Any]) -> None:
    """Marca Redis como caido y activa el backoff del modulo."""
    state["client"] = None
    state["down_until"] = time.monotonic() + REDIS_BACKOFF_S


def redis_client_with_backoff(
    state: dict[str, Any],
    *,
    connect_timeout: float,
    socket_timeout: float,
    verify_ping: bool = False,
    unavailable_log: str | None = None,
    log_logger: logging.Logger | None = None,
):
    """Cliente Redis con timeouts cortos; None sin URL o en backoff tras un fallo."""
    if time.monotonic() < state["down_until"]:
        return None
    if state["client"] is not None:
        return state["client"]
    try:
        import redis as _redis_lib

        from app.core.config import get_settings
        from app.core.redis_retry import no_retry

        url = get_settings().redis_url
        if not url:
            return None
        client = _redis_lib.from_url(
            url, socket_connect_timeout=connect_timeout, socket_timeout=socket_timeout, retry=no_retry()
        )
        if verify_ping:
            client.ping()  # Verificar conectividad
    except Exception as exc:
        if unavailable_log:
            (log_logger or logger).warning(f"{unavailable_log}: {exc}")
        redis_down(state)
        return None
    state["client"] = client
    return client


@asynccontextmanager
async def short_async_redis(redis_url: str):
    """Cliente Redis async de vida corta para guardas; cierra siempre al salir."""
    import redis.asyncio as redis

    from app.core.redis_retry import no_retry_async

    client = redis.from_url(
        redis_url, socket_connect_timeout=1.0, socket_timeout=1.5, retry=no_retry_async()
    )
    try:
        yield client
    finally:
        await client.aclose()
