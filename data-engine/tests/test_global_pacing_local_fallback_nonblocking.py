"""El fallback local de GlobalPacer.wait() no debe bloquear el event loop.

Con Redis caido, la espera del hueco usaba `time.sleep` dentro de la corrutina:
el loop entero (todas las rutas del proceso) se paraba durante el intervalo.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.services.connectors.global_pacing import GlobalPacer


def _fake_clock_pacer(key: str, interval: float, sleep_async):
    clock = [100.0]
    pacer = GlobalPacer(key, min_interval_seconds=interval, redis_client_factory=lambda: None,
                        monotonic=lambda: clock[0], sleep_async=sleep_async)
    return pacer, clock


def test_local_fallback_wait_yields_to_the_event_loop():
    """Sin relojes de pared: la espera cede el control al loop si otra tarea
    puede avanzar MIENTRAS el hueco duerme (antes: ticker real y ticks >= 5)."""
    ran_during_wait: list[bool] = []
    box: dict = {}

    async def sleep_async(seconds):
        box["clock"][0] += seconds
        other = asyncio.create_task(asyncio.sleep(0))  # otra tarea del loop
        await other  # solo termina si el loop no esta bloqueado por esta espera
        ran_during_wait.append(other.done())

    pacer, clock = _fake_clock_pacer("fallback-nonblocking", 0.3, sleep_async)
    box["clock"] = clock

    async def main():
        await pacer.wait()  # primer hueco: sin espera
        assert ran_during_wait == []
        await pacer.wait()  # segundo: espera 0,3 s simulados

    asyncio.run(main())
    assert ran_during_wait == [True]
    assert clock[0] == pytest.approx(100.3)


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
    """Un cool_down() que llega mientras un waiter duerme se respeta (reloj simulado;
    antes un cooler real a 30 ms podia llegar tras despertar el waiter a 150 ms)."""
    sleeps: list[float] = []
    box: dict = {}

    async def sleep_async(seconds):
        sleeps.append(round(seconds, 6))
        if len(sleeps) == 1:
            box["pacer"].cool_down(0.4)  # llega durante la espera
        box["clock"][0] += seconds

    pacer, clock = _fake_clock_pacer("fallback-cooldown", 0.15, sleep_async)
    box.update(pacer=pacer, clock=clock)

    async def main() -> float:
        await pacer.wait()  # consume el primer hueco
        t0 = clock[0]
        await pacer.wait()  # duerme 0,15; el cooldown llega durante la espera
        return clock[0] - t0

    salida = asyncio.run(main())
    assert len(sleeps) >= 2  # revalido al despertar
    assert salida >= 0.4, f"salio a {salida:.3f}s con cooldown pendiente"


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


def test_local_fallback_logs_a_throttled_warning(caplog):
    import logging

    pacer = GlobalPacer("fallback-log", min_interval_seconds=0.01, redis_client_factory=lambda: None)

    async def main():
        for _ in range(3):
            await pacer.wait()

    with caplog.at_level(logging.WARNING):
        asyncio.run(main())
    avisos = [r for r in caplog.records if "usando pacing local" in r.getMessage()]
    assert len(avisos) == 1  # limitado a 1 por minuto
