"""Per-process bounded Yahoo batch work and per-symbol singleflight.

No executor queue: at most four unfinished vendor calls across all batch
requests in this API process. A timed-out request never frees a still-running
call's slot. Other requests can share it, but cannot create unbounded orphans.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait


class QuoteBatchPool:
    def __init__(self, capacity: int = 4):
        self.capacity = capacity
        self.executor = ThreadPoolExecutor(max_workers=capacity, thread_name_prefix='yahoo-batch')
        self.lock = threading.RLock()
        self.inflight: dict[str, Future] = {}

    def submit(self, symbol: str, fetch: Callable[[str], dict | None]) -> Future | None:
        with self.lock:
            if symbol in self.inflight:
                return self.inflight[symbol]
            if len(self.inflight) >= self.capacity:
                return None
            future = self.executor.submit(fetch, symbol)
            self.inflight[symbol] = future

            def completed(done):
                with self.lock:
                    if self.inflight.get(symbol) is done:
                        self.inflight.pop(symbol)

            future.add_done_callback(completed)
            return future

    def fetch(self, symbols: list[str], fetch: Callable[[str], dict | None], deadline: float) -> dict:
        pending = list(symbols)
        active: dict[Future, str] = {}
        result = dict.fromkeys(symbols)
        while (pending or active) and time.monotonic() < deadline:
            for symbol in pending[:]:
                future = self.submit(symbol, fetch)
                if future is not None:
                    active[future] = symbol
                    pending.remove(symbol)
            if not active:
                break  # all slots belong to other requests; fail fast, no queue
            done, _ = wait(active, timeout=max(0, deadline - time.monotonic()), return_when=FIRST_COMPLETED)
            if not done:
                break
            for future in done:
                symbol = active.pop(future)
                try:
                    result[symbol] = future.result()
                except Exception:
                    result[symbol] = None
        return result

    def close(self):
        self.executor.shutdown(wait=True)
