"""El fallback local de GlobalPacer.wait() no debe bloquear el event loop.

Con Redis caido, la espera del hueco usaba `time.sleep` dentro de la corrutina:
el loop entero (todas las rutas del proceso) se paraba durante el intervalo.
"""

from __future__ import annotations

import asyncio
import time

from app.services.connectors.global_pacing import GlobalPacer


def test_local_fallback_wait_yields_to_the_event_loop():
    pacer = GlobalPacer("fallback-nonblocking", min_interval_seconds=0.3, redis_client_factory=lambda: None)
    ticks: list[float] = []

    async def ticker():
        while True:
            ticks.append(time.monotonic())
            await asyncio.sleep(0.02)

    async def main() -> float:
        await pacer.wait()  # primer hueco: sin espera
        task = asyncio.create_task(ticker())
        t0 = time.monotonic()
        await pacer.wait()  # segundo: espera ~0,3 s
        waited = time.monotonic() - t0
        task.cancel()
        return waited

    waited = asyncio.run(main())
    assert waited >= 0.25
    # Con sleep bloqueante el ticker no avanzaba durante la espera.
    assert len(ticks) >= 5, f"el event loop estuvo bloqueado durante la espera: {len(ticks)} ticks"


def test_local_fallback_keeps_the_interval_between_concurrent_waiters():
    pacer = GlobalPacer("fallback-concurrent", min_interval_seconds=0.1, redis_client_factory=lambda: None)

    async def main() -> list[float]:
        marks: list[float] = []

        async def one():
            await pacer.wait()
            marks.append(time.monotonic())

        await asyncio.gather(one(), one(), one())
        return sorted(marks)

    marks = asyncio.run(main())
    assert marks[1] - marks[0] >= 0.08
    assert marks[2] - marks[1] >= 0.08


def test_local_fallback_revalidates_cooldown_arriving_during_the_wait():
    """Un cool_down() que llega mientras un waiter duerme se respeta."""
    pacer = GlobalPacer("fallback-cooldown", min_interval_seconds=0.15, redis_client_factory=lambda: None)

    async def main() -> float:
        await pacer.wait()  # consume el primer hueco
        t0 = time.monotonic()

        async def cooler():
            await asyncio.sleep(0.03)
            pacer.cool_down(0.4)  # vence a t0+~0,43

        task = asyncio.create_task(cooler())
        await pacer.wait()  # dormido ~0,15 s; el cooldown llega durante la espera
        await task
        return time.monotonic() - t0

    salida = asyncio.run(main())
    assert salida >= 0.38, f"salio a {salida:.3f}s con cooldown pendiente"

def test_redis_eval_runs_off_the_event_loop():
    """El `eval` sincrono de Redis no debe ejecutarse en el hilo del event loop."""
    import threading

    seen: dict[str, int] = {}

    class SlowRedis:
        def eval(self, *args):
            seen["thread"] = threading.get_ident()
            time.sleep(0.3)
            return 0

    pacer = GlobalPacer("redis-offloop", min_interval_seconds=0.1, redis_client_factory=lambda: SlowRedis())
    ticks: list[float] = []

    async def ticker():
        while True:
            ticks.append(time.monotonic())
            await asyncio.sleep(0.02)

    async def main() -> int:
        task = asyncio.create_task(ticker())
        await asyncio.sleep(0)
        await pacer.wait()
        task.cancel()
        return threading.get_ident()

    loop_thread = asyncio.run(main())
    assert seen["thread"] != loop_thread
    assert len(ticks) >= 5, f"el event loop estuvo bloqueado por Redis: {len(ticks)} ticks"
