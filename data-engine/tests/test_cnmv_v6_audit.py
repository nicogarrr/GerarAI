"""Auditoria v5: wait_sync del GlobalPacer dormia con _local_lock tomado en el
fallback sin Redis; un hilo de NOD/PS esperando bloqueaba el event loop de OIR
(cool_down/wait async toman el mismo lock). Ahora el lock solo lee/actualiza
estado y el sueno ocurre fuera."""

import asyncio
import threading
import time
from pathlib import Path

import httpx

from app.services.connectors import cnmv, cnmv_pacer
from app.services.connectors.global_pacing import GlobalPacer

OIR_HTML = (Path(__file__).parent / "fixtures" / "cnmv_oir_results.html").read_text(encoding="utf-8")


def test_wait_sync_thread_does_not_block_async_waiter_or_loop():
    pacer = cnmv_pacer.cnmv_pacer
    pacer.reset()
    t0 = time.monotonic()
    pacer.cool_down(0.3)
    sync_done: list[float] = []
    sleeping = threading.Event()
    real_sleep = pacer._sleep

    def spy_sleep(seconds):
        sleeping.set()  # el hilo YA esta durmiendo esperando el cooldown
        real_sleep(seconds)

    pacer._sleep = spy_sleep
    worker = threading.Thread(target=lambda: (pacer.wait_sync(), sync_done.append(time.monotonic() - t0)))
    worker.start()
    assert sleeping.wait(2)
    gaps: list[float] = []

    async def heartbeat(stop: asyncio.Event):
        last = time.monotonic()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    async def run():
        stop = asyncio.Event()
        beat = asyncio.create_task(heartbeat(stop))
        await asyncio.sleep(0.03)  # el latido ya esta en marcha antes de que OIR espere
        handler = lambda r: httpx.Response(200, text=OIR_HTML)  # noqa: E731
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await cnmv.fetch_oir_filings(days=1, client=client)
        stop.set()
        await beat

    try:
        asyncio.run(run())
    finally:
        worker.join(3)
        pacer._sleep = real_sleep
        pacer.reset()
    assert sync_done and sync_done[0] >= 0.29  # el hilo sync SI espera el cooldown
    assert len(gaps) >= 5 and max(gaps) < 0.08


def test_wait_sync_revalidates_cooldown_added_while_sleeping():
    """Determinista: reloj simulado, sin hilos ni sleeps reales. El cooldown
    ampliado llega EXACTAMENTE durante el primer sueno (lo inyecta el propio
    sleep falso). Antes usaba el pacer global con cooldown real de 50 ms: con la
    CPU cargada el cooldown vencia antes de que el hilo empezara a esperar, no
    habia sueno y el test fallaba; y con Redis vivo ni siquiera usaba la ruta local."""
    clock = [100.0]
    sleeps: list[float] = []
    pacer = GlobalPacer(
        "cnmv-test", min_interval_seconds=0.01, redis_client_factory=None,
        monotonic=lambda: clock[0], sleep=lambda seconds: slept(seconds),
    )

    def slept(seconds):
        sleeps.append(round(seconds, 6))
        if len(sleeps) == 1:
            pacer.cool_down(0.2)  # llega un Retry-After mayor mientras el hilo duerme
        clock[0] += seconds

    pacer.cool_down(0.05)
    started = clock[0]
    pacer.wait_sync()
    assert sleeps[0] == 0.05
    assert len(sleeps) == 2  # revalido al despertar y espero el resto
    assert clock[0] - started >= 0.2  # respeta el cooldown ampliado (0,05 + 0,15)
    assert pacer.blocked_for() == 0


# ---- cobertura por rama de global_pacing.py (fichero entero tocado) ----

import pytest  # noqa: E402


class _FakeRedis:
    def __init__(self, wait_ms=0, raw=None, fail=False):
        self.wait_ms, self.raw, self.fail = wait_ms, raw, fail
        self.evals = 0

    def eval(self, *args):
        self.evals += 1
        if self.fail:
            raise RuntimeError("redis caido")
        return self.wait_ms

    def get(self, key):
        if self.fail:
            raise RuntimeError("redis caido")
        return self.raw


def _pacer(client, **kw):
    slept: list[float] = []
    p = GlobalPacer("t", min_interval_seconds=1.0, redis_client_factory=lambda: client,
                    sleep=slept.append, **kw)
    return p, slept


def test_invalid_interval_rejected():
    with pytest.raises(ValueError):
        GlobalPacer("x", min_interval_seconds=0)


def test_client_factory_none_and_raising_degrade_to_local():
    assert GlobalPacer("x", min_interval_seconds=1.0)._client() is None

    def boom():
        raise RuntimeError("sin redis")

    assert GlobalPacer("x", min_interval_seconds=1.0, redis_client_factory=boom)._client() is None


def test_wait_sync_redis_slot_sleeps_returned_wait():
    p, slept = _pacer(_FakeRedis(wait_ms=250))
    p.wait_sync()
    assert slept == [0.25]
    p2, slept2 = _pacer(_FakeRedis(wait_ms=0))
    p2.wait_sync()
    assert slept2 == []


def test_wait_sync_redis_failure_falls_back_to_local_without_sleep_when_free():
    p, slept = _pacer(_FakeRedis(fail=True))
    p.wait_sync()
    assert slept == []  # primer uso local: hueco libre


def test_wait_sync_without_fallback_local_returns_immediately():
    p, slept = _pacer(None, fallback_local=False)
    p.wait_sync()
    assert slept == []


def test_cool_down_ignores_non_positive_and_extends_redis():
    client = _FakeRedis()
    p, _ = _pacer(client)
    p.cool_down(0)
    assert client.evals == 0
    p.cool_down(5)
    assert client.evals == 1
    pf, _ = _pacer(_FakeRedis(fail=True))
    pf.cool_down(5)  # fallo de Redis: el cooldown local ya quedo
    assert pf.blocked_for() > 0


def test_blocked_for_remote_all_paths():
    assert GlobalPacer("x", min_interval_seconds=1.0).blocked_for_remote() == 0.0
    assert _pacer(_FakeRedis(raw=None))[0].blocked_for_remote() == 0.0
    p = GlobalPacer("x", min_interval_seconds=1.0, redis_client_factory=lambda: _FakeRedis(raw="5000"),
                    wall_clock=lambda: 2.0)
    assert p.blocked_for_remote() == 3.0
    assert _pacer(_FakeRedis(fail=True))[0].blocked_for_remote() == 0.0


def test_blocked_for_merges_redis_probe_and_survives_its_failure():
    p = GlobalPacer("x", min_interval_seconds=1.0, redis_client_factory=lambda: _FakeRedis(raw="9000000000000"))
    assert p.blocked_for() > 1000
    assert _pacer(_FakeRedis(fail=True))[0].blocked_for() == 0.0
    assert _pacer(_FakeRedis(raw=None))[0].blocked_for() == 0.0


def test_log_local_fallback_rate_limited():
    p = GlobalPacer("x", min_interval_seconds=1.0)
    p._log_local_fallback(True)
    first = p._last_fallback_log
    p._log_local_fallback(False)  # dentro del minuto: no relogea
    assert p._last_fallback_log == first


class _AtomicRedis:
    """Redis falso atomico que imita la semantica de los dos Lua del pacer."""

    def __init__(self):
        self.data: dict[str, int] = {}
        self.lock = threading.Lock()

    def eval(self, script, nkeys, *args):
        with self.lock:
            if nkeys == 2:
                slot, block, now, interval, _ttl = args
                start = max(now, self.data.get(slot, 0), self.data.get(block, 0))
                self.data[slot] = start + interval
                return max(0, start - now)
            block, until, _ttl = args
            self.data[block] = max(self.data.get(block, 0), until)
            return self.data[block]

    def get(self, key):
        with self.lock:
            return self.data.get(key)


def _simulated_pacer(interval=0.1):
    """Pacer con Redis atomico y reloj simulado (sleep avanza el reloj)."""
    clock = {"t": 1000.0}
    lock = threading.Lock()
    sleeps: list[float] = []

    def now():
        return clock["t"]

    def fake_sleep(seconds):
        with lock:
            sleeps.append(seconds)
            clock["t"] += seconds

    redis = _AtomicRedis()
    p = GlobalPacer("t", min_interval_seconds=interval, redis_client_factory=lambda: redis,
                    wall_clock=now, monotonic=now, sleep=fake_sleep)
    return p, clock, sleeps, redis


def test_wait_sync_redis_path_re_reserves_slot_after_cooldown_added_while_sleeping():
    p, clock, sleeps, _ = _simulated_pacer(interval=0.1)
    p.wait_sync()  # primer uso: sin espera
    p.wait_sync()  # hueco +0,1 s
    assert sleeps == [pytest.approx(0.1)]
    # segundo esperador reserva hueco; mientras duerme llega un cooldown de 2 s
    original = p._sleep

    def sleep_then_cooldown(seconds):
        original(seconds)
        if not getattr(sleep_then_cooldown, "done", False):
            sleep_then_cooldown.done = True
            p.cool_down(2.0)

    p._sleep = sleep_then_cooldown
    start = clock["t"]
    p.wait_sync()
    assert clock["t"] - start >= 2.0  # respeta el cooldown ampliado
    assert p.blocked_for() <= 0


def test_two_sync_waiters_stay_separated_after_midwait_cooldown():
    """Auditor stack6: dos esperadores con cooldown sobrevenido NO se sueltan a la vez."""
    redis = _AtomicRedis()
    sleeping = threading.Event()
    count = [0]
    lock = threading.Lock()

    def sleep(seconds):
        with lock:
            count[0] += 1
            if count[0] >= 2:
                sleeping.set()
        time.sleep(seconds)

    p = GlobalPacer("audit", min_interval_seconds=0.10, redis_client_factory=lambda: redis, sleep=sleep)
    p.wait_sync()
    done: list[float] = []

    def call():
        p.wait_sync()
        done.append(time.monotonic())

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    assert sleeping.wait(2)
    p.cool_down(0.35)
    for t in threads:
        t.join(3)
    assert len(done) == 2
    assert abs(done[1] - done[0]) >= 0.09


def test_two_async_waiters_stay_separated_after_midwait_cooldown():
    import asyncio

    redis = _AtomicRedis()
    state = {"sleeping": 0}
    done: list[float] = []

    async def run():
        entered = asyncio.Event()

        async def sleep_async(seconds):
            state["sleeping"] += 1
            if state["sleeping"] >= 2:
                entered.set()
            await asyncio.sleep(seconds)

        p = GlobalPacer("audit", min_interval_seconds=0.10, redis_client_factory=lambda: redis,
                        sleep_async=sleep_async)
        await p.wait()

        async def call():
            await p.wait()
            done.append(time.monotonic())

        tasks = [asyncio.create_task(call()) for _ in range(2)]
        await asyncio.wait_for(entered.wait(), 2)
        p.cool_down(0.35)
        await asyncio.gather(*tasks)

    asyncio.run(run())
    assert len(done) == 2
    assert abs(done[1] - done[0]) >= 0.09


def test_wait_redis_path_respects_cooldown_added_while_sleeping_async():
    import asyncio

    p, clock, sleeps, _ = _simulated_pacer(interval=0.1)
    asyncio.run(p.wait())

    async def fake_sleep_async(seconds):
        sleeps.append(seconds)
        clock["t"] += seconds
        if not getattr(fake_sleep_async, "done", False):
            fake_sleep_async.done = True
            p.cool_down(2.0)

    p._sleep_async = fake_sleep_async
    start = clock["t"]
    asyncio.run(p.wait())
    assert clock["t"] - start >= 2.0
