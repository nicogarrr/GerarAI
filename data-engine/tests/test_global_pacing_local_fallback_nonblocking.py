"""El fallback local de GlobalPacer.wait() no debe bloquear el event loop.

Con Redis caido, la espera del hueco usaba `time.sleep` dentro de la corrutina:
el loop entero (todas las rutas del proceso) se paraba durante el intervalo.
"""

from __future__ import annotations

import asyncio

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
    """Tiempo virtual: cada durmiente despierta EXACTAMENTE en su hueco, sin cotas
    de pared (antes: marks con time.monotonic y gaps >= 0.08; un durmiente que
    despertaba tarde con el loop cargado acercaba su marca a la del siguiente)."""
    import heapq

    now = [100.0]
    pending: list = []
    seq = [0]

    async def sleep_async(seconds):
        fut = asyncio.get_running_loop().create_future()
        seq[0] += 1
        heapq.heappush(pending, (now[0] + seconds, seq[0], fut))
        await fut

    pacer = GlobalPacer("fallback-concurrent", min_interval_seconds=0.1, redis_client_factory=lambda: None,
                        monotonic=lambda: now[0], sleep_async=sleep_async)

    async def main() -> list[float]:
        marks: list[float] = []

        async def one():
            await pacer.wait()
            marks.append(now[0])

        tasks = [asyncio.create_task(one()) for _ in range(3)]
        while not all(t.done() for t in tasks):
            await asyncio.sleep(0)  # los durmientes ya estan en su sleep
            if pending:
                target, _, fut = heapq.heappop(pending)
                now[0] = max(now[0], target)
                fut.set_result(None)
        return marks

    marks = asyncio.run(main())
    assert [round(m - 100.0, 6) for m in marks] == [0.0, 0.1, 0.2]  # un hueco por waiter, a su hora


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
    """El `eval` sincrono de Redis no debe ejecutarse en el hilo del event loop.

    Sin relojes de pared: el eval se queda bloqueado hasta que el test lo
    suelta, y mientras tanto otra corrutina debe seguir avanzando (antes:
    sleep(0.3) real y >=5 ticks de un ticker a 20 ms, una cota inferior de
    pared que dependia de la carga del runner).
    """
    import threading

    seen: dict[str, int] = {}
    eval_started = threading.Event()
    release_eval = threading.Event()

    class SlowRedis:
        def eval(self, *args):
            seen["thread"] = threading.get_ident()
            eval_started.set()
            # Bloqueo «largo» controlado: solo el test lo suelta. El tope
            # evita colgar la suite si el loop estuviera bloqueado (el test
            # falla entonces por el assert de hilos, no por un cuelgue).
            release_eval.wait(timeout=3)
            return 0

    pacer = GlobalPacer("redis-offloop", min_interval_seconds=0.1, redis_client_factory=lambda: SlowRedis())
    ticks: list[int] = []

    async def ticker():
        while True:
            ticks.append(1)
            await asyncio.sleep(0)

    async def main() -> int:
        tick_task = asyncio.create_task(ticker())
        wait_task = asyncio.create_task(pacer.wait())
        loop = asyncio.get_running_loop()
        start = loop.time()  # solo como guarda anti-cuelgue, no como asercion
        while not eval_started.is_set():
            if loop.time() - start > 10:
                tick_task.cancel()
                raise AssertionError("el eval no llego a empezar: el hilo executor no progresa")
            await asyncio.sleep(0)
        antes = len(ticks)
        for _ in range(3):
            await asyncio.sleep(0)
        assert len(ticks) > antes, "el event loop estuvo bloqueado durante el eval de Redis"
        release_eval.set()
        await wait_task
        tick_task.cancel()
        return threading.get_ident()

    loop_thread = asyncio.run(main())
    assert seen["thread"] != loop_thread


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
