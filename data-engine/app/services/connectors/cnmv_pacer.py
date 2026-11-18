"""Pacer global «cnmv» UNICO para todo el sitio cnmv.es (NOD, PS, cortos...).

Auditoria 2026-11-18 (3): antes cada conector instanciaba su propio
GlobalPacer("cnmv"). Con Redis vivo daba igual (los slots comparten clave),
pero con Redis caido cada instancia caia a SU fallback local (lock, next y
blocked_until propios): NOD y PS podian disparar 1 req/s CADA UNO sobre el
mismo sitio, doblando el ritmo declarado. Un solo modulo = una sola
instancia por proceso, y el fallback local es uno solo para todo cnmv.es.
"""

from __future__ import annotations

import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from app.services.connectors.global_pacing import GlobalPacer

MIN_INTERVAL_S = 1.0  # 1 peticion/s GLOBAL al sitio CNMV (todos los procesos)
CNMV_HOST = "www.cnmv.es"


def is_cnmv_url(url: str) -> bool:
    """Allowlist estricta de descarga para los conectores CNMV (NOD, PS): solo
    https al host EXACTO www.cnmv.es. Se pasa a app.services.public_fetch como
    ``allowed_url``, que la aplica a la URL inicial y a CADA redireccion."""
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == CNMV_HOST and parsed.port in (None, 443)


def _cnmv_redis_client():
    try:
        import redis as _redis

        from app.core.config import get_settings
        from app.core.redis_retry import no_retry

        url = get_settings().redis_url
        if not url:
            return None
        return _redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=1.0, retry=no_retry())
    except Exception:  # noqa: BLE001 - sin Redis: pacing local por proceso
        return None


# Instancia unica por proceso: serializa hilos (lock local) y procesos
# (slots Redis, mismo mecanismo que finnhub/gdelt).
cnmv_pacer = GlobalPacer(
    "cnmv",
    min_interval_seconds=MIN_INTERVAL_S,
    redis_client_factory=_cnmv_redis_client,
)


def respect_retry_after(response: httpx.Response) -> None:
    """Retry-After INTEGRO (segundos o HTTP-date) -> cooldown GLOBAL extend-only.

    Parser unico para TODOS los conectores de cnmv.es (OIR, NOD, PS). Antes NOD
    solo aceptaba la forma numerica e ignoraba una HTTP-date valida (auditoria
    2026-11-18). Nunca se recorta: un Retry-After grande bloquea todas las
    llamadas a cnmv.es de todos los procesos hasta que expire; el actor falla,
    Dramatiq reintenta por backoff y la corrida siguiente ya encuentra el
    cooldown vencido. Valor ilegible: 60 s (conservador, declarado).
    """
    value = response.headers.get("Retry-After")
    if not value:
        return
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            seconds = max(when.timestamp() - time.time(), 0.0)
        except (TypeError, ValueError):
            seconds = 60.0
    cnmv_pacer.cool_down(seconds)
