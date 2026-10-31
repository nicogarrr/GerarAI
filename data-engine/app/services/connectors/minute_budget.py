"""Presupuesto compartido de llamadas por minuto a un proveedor de datos.

A diferencia de un semáforo (que acota CONCURRENCIA), esto acota el RITMO:
el plan gratis de Finnhub son 60 llamadas/minuto (finnhub.io/pricing,
consultada 2026-09-26) y el refresco de mercado solo acotaba a 6 peticiones
en vuelo. Con respuestas de ~0.2 s, 6 en vuelo son ~1800 llamadas/minuto:
429 en racha, y el servicio marcaba el proveedor como caído (null por
ticker) perdiendo la corrida entera aunque el límite era solo de ritmo.

El presupuesto es UNA instancia por proveedor a nivel de proceso, compartida
por todas las tareas que lo llaman (refresco, IR, métricas, eventos): así el
reparto entre tareas es automático - ninguna combinación de consumidores
puede superar el límite del plan. La espera es asyncio.sleep FUERA del
cerrojo: nunca congela el event loop.

Solo proceso, sin Redis (carril de otro agente): en multi-proceso cada
proceso tendría su propio presupuesto. La clase aísla el contrato
(``acquire`` async) para que sustituir el backend sea local a este módulo.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable


class MinuteBudget:
    """Ventana rodante de N llamadas por minuto, async y sin bloquear el loop.

    ``acquire()`` registra UNA llamada intentada (las fallidas también las
    cuenta el proveedor). Si la ventana está llena, duerme lo justo hasta que
    expire la llamada más antigua y reintenta.

    El cerrojo es ``threading.Lock`` (como el limitador de Alpha Vantage):
    hay consumidores que llaman al cliente desde hilos vía ``_await_sync`` y
    un ``asyncio.Lock`` quedaría ligado al primer event loop que lo usara.
    El cerrojo solo cubre el acceso O(1) al deque; la espera es siempre
    ``asyncio.sleep`` fuera de él. El reloj y el sleep son inyectables para
    tests deterministas.
    """

    def __init__(
        self,
        limit: int,
        *,
        window_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if int(limit) <= 0:
            raise ValueError(f"limit debe ser > 0, recibido {limit}")
        self.limit = int(limit)
        self.window = float(window_seconds)
        self._clock: Callable[[], float] = clock or time.monotonic
        self._sleep: Callable[[float], Awaitable[None]] = sleep or asyncio.sleep
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        horizon = now - self.window
        while self._calls and self._calls[0] <= horizon:
            self._calls.popleft()

    async def acquire(self) -> None:
        while True:
            with self._lock:
                now = self._clock()
                self._prune(now)
                if len(self._calls) < self.limit:
                    self._calls.append(now)
                    return
                wait = self._calls[0] + self.window - now
            await self._sleep(max(wait, 0.0))

    def calls_in_window(self) -> int:
        """Llamadas registradas en la ventana actual (observabilidad/tests)."""
        with self._lock:
            self._prune(self._clock())
            return len(self._calls)
