import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.api.routes import market


def test_batch_returns_before_slow_vendor_and_shares_inflight(monkeypatch):
    market._quote_cache.clear()
    monkeypatch.setattr(market, '_batch_redis_client', lambda: None)
    monkeypatch.setattr(market, '_QUOTES_BATCH_DEADLINE_SECONDS', .04, raising=False)
    release = threading.Event()
    lock = threading.Lock()
    calls = []

    def fetch(client, symbol):
        with lock:
            calls.append(symbol)
        release.wait(.4)
        return {'c': 10}

    monkeypatch.setattr(market, '_fetch_yahoo_quote', fetch)
    start = time.monotonic()
    try:
        with ThreadPoolExecutor(8) as callers:
            results = list(callers.map(lambda _: market.market_quotes_batch(
                market.MarketQuotesBatchIn(symbols=['SLOW-ONE'])), range(8)))
        assert time.monotonic() - start < .25
        assert calls == ['SLOW-ONE']
        assert all(r == {'quotes': {'SLOW-ONE': None}} for r in results)
    finally:
        release.set()
        with market._quote_batch_pool.lock:
            running = list(market._quote_batch_pool.inflight.values())
        for future in running:
            future.result(timeout=1)


def test_pool_never_queues_more_than_global_capacity_after_timeouts():
    from app.services.bounded_quote_batch import QuoteBatchPool

    pool = QuoteBatchPool(2)
    release = threading.Event()
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        release.wait(1)
        return {'c': 1}

    try:
        assert pool.fetch(['A', 'B', 'C'], fetch, time.monotonic() + .03) == dict.fromkeys(['A', 'B', 'C'])
        assert pool.fetch(['D', 'E'], fetch, time.monotonic() + .03) == {'D': None, 'E': None}
        assert sorted(calls) == ['A', 'B']
        with pool.lock:
            assert len(pool.inflight) == 2
    finally:
        release.set()
        pool.close()


def test_fast_batch_drains_more_than_one_wave_and_handles_errors():
    from app.services.bounded_quote_batch import QuoteBatchPool

    pool = QuoteBatchPool(2)
    try:
        def fetch(symbol):
            if symbol == 'FAIL':
                raise RuntimeError('vendor')
            return {'c': len(symbol)}

        assert pool.fetch(['A', 'BB', 'CCC', 'FAIL'], fetch, time.monotonic() + 1) == {
            'A': {'c': 1}, 'BB': {'c': 2}, 'CCC': {'c': 3}, 'FAIL': None,
        }
        assert pool.fetch(['TOO-LATE'], fetch, time.monotonic() - 1) == {'TOO-LATE': None}
    finally:
        pool.close()


def test_fast_result_not_delayed_by_slow_peer():
    from app.services.bounded_quote_batch import QuoteBatchPool

    pool = QuoteBatchPool(2)
    release = threading.Event()
    try:
        def fetch(symbol):
            if symbol == 'SLOW':
                release.wait(1)
            return {'c': 1}

        out = pool.fetch(['FAST', 'SLOW'], fetch, time.monotonic() + .04)
        assert out == {'FAST': {'c': 1}, 'SLOW': None}
    finally:
        release.set()
        pool.close()
