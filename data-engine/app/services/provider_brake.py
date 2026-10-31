"""Freno por proveedor en Redis: pausa el carril de un proveedor tras una
racha de 429, con TTL y estado visible.

Orden de Nico (31-oct-2026): colas que no se atasquen. Patron medido en prod
con GDELT: rachas de 3-16 respuestas 429 por IP con reintentos de 4-5 min
quemaban los hilos del carril sin progreso. El freno convierte la racha en
una pausa con TTL: los actores del carril skippean (ticks nuevos) o se
reprograman (trabajo ya aceptado) mientras dure, y el estado se lee en
/health/data-sources.

Complementario del limitador de ritmo en Redis (carril de perf): aquel
modula la ADMISION por ritmo; este freno se dispara por FALLOS (429) y pausa
el carril entero. No duplican: un proveedor puede tener ambos.

SEC y GDELT ya tienen breakers propios auditados (sec_breaker:* y
gdelt:circuit:*): NO se migran a este modulo; el lector de estado los
incluye tal cual para que la visibilidad sea completa.

Fail-open en todo: Redis caido no frena nada (un duplicado de trabajo lo
absorben los leases/coalescing del carril; perder el tick seria peor).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_KEY_PREFIX = "provider_brake"


@dataclass(frozen=True)
class BrakeConfig:
    """Racha que abre el freno, ventana de la racha y pausa (TTL) al abrir."""

    streak_limit: int
    window_s: int
    cooldown_s: int


# Solo carriles SIN breaker propio. sec (sec_breaker:*) y gdelt
# (gdelt:circuit:*) ya pausan su cola con TTL; registrarlos aqui duplicaria.
PROVIDER_BRAKES: dict[str, BrakeConfig] = {
    # Carril ticker-news (cola default): ~1 req/1,5 s por IP contra Yahoo
    # Finance RSS y Google News RSS. Sin freno, una racha de 429 repite el
    # patron medido en GDELT sobre el worker de default (1 hilo).
    "yahoo": BrakeConfig(streak_limit=3, window_s=600, cooldown_s=1800),
    "google-news": BrakeConfig(streak_limit=3, window_s=600, cooldown_s=1800),
}


def _open_key(provider: str) -> str:
    return f"{_KEY_PREFIX}:{provider}:open"


def _streak_key(provider: str) -> str:
    return f"{_KEY_PREFIX}:{provider}:429_streak"


def _config(provider: str) -> BrakeConfig:
    try:
        return PROVIDER_BRAKES[provider]
    except KeyError:
        raise ValueError(
            f"proveedor sin freno registrado: {provider!r} "
            f"(registrados: {sorted(PROVIDER_BRAKES)})"
        ) from None


def is_open(client, provider: str) -> bool:
    """True si el freno del proveedor esta abierto. Fail-open: False."""
    _config(provider)
    try:
        return client is not None and bool(client.get(_open_key(provider)))
    except Exception:  # noqa: BLE001 - sonda best-effort
        return False


def record_429(client, provider: str) -> bool:
    """Cuenta un 429 del proveedor; True si la racha abre el freno.

    Contador atomico (INCR) compartido por TODOS los procesos, con la
    ventana puesta solo en el primer incremento. Al cruzar el umbral se
    abre la pausa (SET EX cooldown, idempotente) y se resetea la racha.
    Carrera benigna: dos hilos pueden cruzar el umbral a la vez; ambos
    hacen el mismo SET. Fail-open: Redis roto devuelve False (sin freno).
    """
    config = _config(provider)
    if client is None:
        return False
    try:
        streak = client.incr(_streak_key(provider))
        if streak == 1:
            client.expire(_streak_key(provider), config.window_s)
        if streak >= config.streak_limit:
            client.set(_open_key(provider), "1", ex=config.cooldown_s)
            client.delete(_streak_key(provider))
            return True
    except Exception:  # noqa: BLE001 - best-effort
        logger.warning("provider_brake: Redis fallo registrando racha de %s; fail-open", provider, exc_info=True)
    return False


def record_success(client, provider: str) -> None:
    """Un exito rompe la racha (el freno abierto caduca solo por TTL)."""
    _config(provider)
    try:
        if client is not None:
            client.delete(_streak_key(provider))
    except Exception:  # noqa: BLE001 - best-effort
        logger.warning("provider_brake: Redis fallo rompiendo racha de %s", provider, exc_info=True)


def open_brakes(client) -> list[dict[str, Any]]:
    """Frenos abiertos con su TTL restante, para /health/data-sources.

    Incluye los breakers legacy (gdelt, sec) con sus claves propias para
    que el estado visible sea el cuadro completo. Solo lectura; cero
    llamadas HTTP. Fail-open: lista vacia si Redis no responde.
    """
    if client is None:
        return []
    brakes: list[dict[str, Any]] = []
    try:
        legacy = (("gdelt", "gdelt:circuit:open"), ("sec", "sec_breaker:open"))
        generic = [(p, _open_key(p)) for p in PROVIDER_BRAKES]
        for provider, key in [*legacy, *generic]:
            if client.get(key):
                ttl = client.ttl(key)
                brakes.append(
                    {
                        "provider": provider,
                        "key": key,
                        "ttl_seconds": ttl if isinstance(ttl, int) and ttl >= 0 else None,
                    }
                )
    except Exception:  # noqa: BLE001 - solo lectura, fail-open
        return []
    return brakes
