"""Pacing GLOBAL (Redis) para proveedores con cuota compartida por clave/IP.

Medido en prod (31-oct-2026, piloto): 1.077 HTTP 429 de Finnhub en 10 min con
2 refresh_valuation_metrics en vuelo, y GDELT en rachas de 3-16 429 que abrian
el disyuntor 30 min sin ingesta real. Cada proceso (workers, scheduler, API)
llevaba su propio reloj: el ritmo AGREGADO superaba la cuota aunque cada
proceso se creyera dentro. El estado del ritmo tiene que vivir en Redis, que
es lo unico compartido por todos los procesos.

Sin Redis (dev/tests) degrada a un limitador por proceso: nunca a "sin
pacing". El hueco se reserva de forma atomica ANTES de dormir (claim-first):
dos procesos no pueden salir a la vez y un overrun solo empuja el hueco
siguiente hacia fuera.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Reserva atomica del siguiente hueco: start = max(ahora, hueco, cooldown);
# guarda start+intervalo y devuelve la espera en ms. Un solo round-trip.
_CLAIM_SLOT_LUA = """
local now = tonumber(ARGV[1])
local interval = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local next_slot = tonumber(redis.call('GET', KEYS[1]) or '0') or 0
local blocked = tonumber(redis.call('GET', KEYS[2]) or '0') or 0
local start = math.max(now, next_slot, blocked)
redis.call('SET', KEYS[1], string.format('%.0f', start + interval), 'PX', ttl)
return math.max(0, start - now)
"""

# Cooldown 429 extend-only: una ventana marcada nunca se acorta (dos 429
# seguidos se quedan con la mayor). Devuelve el fin de ventana vigente (ms).
_EXTEND_COOLDOWN_LUA = """
local until_ms = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local current = tonumber(redis.call('GET', KEYS[1]) or '0') or 0
if until_ms > current then
  redis.call('SET', KEYS[1], string.format('%.0f', until_ms), 'PX', ttl)
end
return math.max(current, until_ms)
"""


class GlobalPacer:
    """Separador global entre peticiones a un proveedor (todos los procesos).

    - ``wait()``: reserva el siguiente hueco global y duerme lo que falte.
    - ``cool_down(seconds)``: marca un cooldown 429 extend-only (Retry-After).
    - ``blocked_for()``: segundos de cooldown restantes (0 si no hay).
    """

    def __init__(
        self,
        key: str,
        *,
        min_interval_seconds: float,
        redis_client_factory: Callable[[], Any | None] | None = None,
        wall_clock: Callable[[], float] = time.time,
        slot_ttl_ms: int = 120_000,
        fallback_local: bool = True,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_interval_seconds <= 0:
            raise ValueError(f"min_interval_seconds debe ser > 0, recibido {min_interval_seconds}")
        self.key = key
        self.min_interval_seconds = float(min_interval_seconds)
        self._factory = redis_client_factory
        self._wall = wall_clock
        self._slot_ttl_ms = slot_ttl_ms
        self._fallback_local = fallback_local
        # Reloj/sleep inyectables: los tests fijan el comportamiento con Redis
        # caido SIN desactivar el fallback local (proteccion de prod).
        self._monotonic = monotonic
        self._sleep = sleep
        self._local_next = 0.0
        self._local_blocked_until = 0.0
        self._local_lock = threading.Lock()

    @property
    def _slot_key(self) -> str:
        return f"global_pacer:{self.key}:next"

    @property
    def _cooldown_key(self) -> str:
        return f"global_pacer:{self.key}:blocked_until"

    def _client(self) -> Any | None:
        if self._factory is None:
            return None
        try:
            return self._factory()
        except Exception:  # noqa: BLE001 - fail-open al pacing local
            return None

    async def wait(self) -> None:
        """Bloquea (async) hasta el siguiente hueco global del proveedor."""
        interval_ms = int(self.min_interval_seconds * 1000)
        client = self._client()
        if client is not None:
            try:
                now_ms = int(self._wall() * 1000)
                wait_ms = client.eval(
                    _CLAIM_SLOT_LUA, 2, self._slot_key, self._cooldown_key,
                    now_ms, interval_ms, self._slot_ttl_ms,
                )
                wait = max(0.0, float(wait_ms) / 1000.0)
                if wait > 0:
                    await asyncio.sleep(wait)
                return
            except Exception as exc:  # noqa: BLE001 - Redis caido: pacing local
                logger.warning("global pacer %s: Redis unavailable, fallback local: %s", self.key, exc)
        if not self._fallback_local:
            # Proveedor SIN pacing previo (Finnhub): con Redis caido se mantiene
            # el comportamiento actual (ninguno) en vez de degradar dev/tests
            # con esperas que en prod no protegen nada (alli Redis existe).
            return
        with self._local_lock:
            while True:
                now = self._monotonic()
                remaining = max(self._local_next, self._local_blocked_until) - now
                if remaining <= 0:
                    break
                self._sleep(remaining)
            self._local_next = self._monotonic() + self.min_interval_seconds

    def cool_down(self, seconds: float) -> None:
        """Marca un cooldown 429 (extend-only) visible por TODOS los procesos."""
        if seconds <= 0:
            return
        with self._local_lock:
            until = self._monotonic() + seconds
            if until > self._local_blocked_until:
                self._local_blocked_until = until
        client = self._client()
        if client is None:
            return
        try:
            until_ms = int((self._wall() + seconds) * 1000)
            client.eval(_EXTEND_COOLDOWN_LUA, 1, self._cooldown_key, until_ms, int(seconds * 1000) + 5000)
        except Exception:  # noqa: BLE001 - best-effort, el cooldown local ya quedo
            pass

    def blocked_for_remote(self) -> float:
        """Segundos de cooldown leidos SOLO de Redis (0 si no hay o no responde).

        Para consumidores con reloj propio (GDELT usa time.monotonic y los
        tests lo sustituyen): el cooldown LOCAL del pacer vive en otro reloj
        y no debe mezclarse en su espera; el valor de Redis llega como
        duracion en segundos, comparable con deltas de monotonic.
        """
        client = self._client()
        if client is None:
            return 0.0
        try:
            raw = client.get(self._cooldown_key)
            if raw is None:
                return 0.0
            return max(0.0, float(raw) / 1000.0 - self._wall())
        except Exception:  # noqa: BLE001 - sonda best-effort
            return 0.0

    def blocked_for(self) -> float:
        """Segundos de cooldown restantes (0 si no hay)."""
        remaining = 0.0
        with self._local_lock:
            remaining = max(0.0, self._local_blocked_until - time.monotonic())
        client = self._client()
        if client is not None:
            try:
                raw = client.get(self._cooldown_key)
                if raw is not None:
                    remaining = max(remaining, float(raw) / 1000.0 - self._wall())
            except Exception:  # noqa: BLE001 - sonda best-effort
                pass
        return max(0.0, remaining)

    def reset(self) -> None:
        """Solo para tests: olvida el pacing local (el de Redis expira por TTL)."""
        with self._local_lock:
            self._local_next = 0.0
            self._local_blocked_until = 0.0
