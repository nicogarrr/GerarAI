"""The process-local fallback is shared by independent ASGI event loops."""
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.core import rate_limit


def test_local_counter_is_atomic_across_event_loops(monkeypatch):
    class SlowStore(dict):
        def setdefault(self, key, default):
            # Force contention while the first caller holds the real lock.
            time.sleep(0.02)
            return super().setdefault(key, default)

    monkeypatch.setattr(rate_limit, "_local_hits", SlowStore())
    barrier = threading.Barrier(4)

    async def hit():
        return await asyncio.wait_for(rate_limit._record_hit(
            "same-user", window_seconds=60, use_redis=False,
            redis_url="", degrade_to_local=True), timeout=2)

    def from_independent_loop(_):
        barrier.wait(timeout=5)
        return asyncio.run(hit())[0]

    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = list(pool.map(from_independent_loop, range(4)))
    assert sorted(counts) == [1, 2, 3, 4]
    assert asyncio.run(rate_limit._count_hits("same-user", use_redis=False, redis_url="")) == 4
