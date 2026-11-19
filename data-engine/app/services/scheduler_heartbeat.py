"""Latido del planificador: quien vigila al vigilante.

Motivo (medido 18-nov-2026): todos los watchdogs in-app (colas, salud de
fuentes, conexiones PG, frescura) los dispara el planificador
(cavaai-scheduler). Si ese proceso muere, se cuelga o un job deja de
registrarse, TODO queda en silencio y el panel parece sano: ningun
watchdog puede alertar de su propia muerte.

Contrato: el planificador registra un listener sobre EVENT_JOB_EXECUTED;
cada job que TERMINA BIEN escribe su latido en Redis (clave
``scheduler:heartbeat:<job_id>``, valor ISO UTC). Un job que falla no
escribe latido. La escritura es fail-open: un Redis caido nunca rompe un
job, se loguea y se devuelve False. El chequeo lo hace
scripts/ops/check-scheduler-heartbeat.sh desde el host por cron: sin
latido, latido ilegible o latido viejo = alerta (exit 1).
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

KEY_PREFIX = "scheduler:heartbeat:"

_clients: dict[str, Any] = {}
_clients_lock = threading.Lock()


def heartbeat_key(job_id: str) -> str:
    return f"{KEY_PREFIX}{job_id}"


def record(client: Any, job_id: str, *, now: datetime | None = None) -> None:
    """Escribe el latido con un cliente dado (pura, testeable)."""
    ts = (now or datetime.now(UTC)).isoformat()
    client.set(heartbeat_key(job_id), ts)


def _client_for(redis_url: str) -> Any:
    """Cliente redis por URL, cacheado (los latidos son a escala de minutos).

    El parametro se llama ``redis_url`` a proposito: el guard AST de
    tests/test_redis_auth_clients.py exige que todo from_url de app/ salga
    de Settings.redis_url (la contrasena viaja solo en esa URL, #3232).
    """
    with _clients_lock:
        client = _clients.get(redis_url)
        if client is None:
            import redis as _redis

            from app.core.redis_retry import no_retry

            client = _redis.from_url(
                redis_url, socket_connect_timeout=2, socket_timeout=2,
                retry=no_retry(),
            )
            _clients[redis_url] = client
        return client


def record_job(job_id: str, *, redis_url: str | None = None) -> bool:
    """Latido desde el listener del planificador.

    Fail-open: si Redis no esta o la escritura falla, loguea y devuelve
    False; NUNCA lanza (un job no puede morir por grabar su propio latido).
    """
    try:
        url = redis_url or get_settings().redis_url
        record(_client_for(url), job_id)
        return True
    except Exception:
        logger.warning(
            "scheduler_heartbeat: no se pudo grabar el latido de %s",
            job_id, exc_info=True,
        )
        return False
