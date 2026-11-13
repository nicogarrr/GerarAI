import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.api.routes import market
from app.services.bounded_quote_batch import QuoteBatchPool


def test_batch_returns_before_slow_vendor_and_shares_inflight(monkeypatch):
    # A private pool and cache keep other market tests out of this contract.
    # Start the vendor before the callers: scheduler latency must not decide
    # whether a 40 ms test window happens to include its first instruction.
    pool = QuoteBatchPool(1)
    monkeypatch.setattr(market, '_quote_batch_pool', pool)
    monkeypatch.setattr(market, '_quote_cache', {})
    monkeypatch.setattr(market, '_batch_redis_client', lambda: None)
    monkeypatch.setattr(market, '_shared_yahoo_client', lambda: object())
    monkeypatch.setattr(market, '_QUOTES_BATCH_DEADLINE_SECONDS', .1)
    release = threading.Event()
    started = threading.Event()
    calls = []

    def fetch(client, symbol):
        calls.append(symbol)
        started.set()
        assert release.wait(10), 'test did not release vendor'
        return {'c': 10}

    monkeypatch.setattr(market, '_fetch_yahoo_quote', fetch)
    callers = ThreadPoolExecutor(8)
    try:
        vendor = pool.submit('SLOW-ONE', lambda symbol: fetch(None, symbol))
        assert started.wait(5), 'vendor worker did not start'
        requests = [callers.submit(
            market.market_quotes_batch,
            market.MarketQuotesBatchIn(symbols=['SLOW-ONE']),
        ) for _ in range(8)]
        results = [request.result(timeout=5) for request in requests]
        # Every request returned while the vendor was still blocked. This
        # proves the deadline without a fragile wall-clock upper bound.
        assert vendor is not None and not vendor.done()
        assert calls == ['SLOW-ONE']
        assert all(r == {'quotes': {'SLOW-ONE': None}} for r in results)
    finally:
        release.set()
        callers.shutdown(wait=True)
        pool.close()


def test_batch_passes_its_absolute_deadline_to_the_pool(monkeypatch):
    captured = []

    class RecordingPool:
        def fetch(self, symbols, fetch, deadline):
            captured.append(deadline)
            return dict.fromkeys(symbols)

    monkeypatch.setattr(market, '_quote_batch_pool', RecordingPool())
    monkeypatch.setattr(market, '_quote_cache', {})
    monkeypatch.setattr(market, '_batch_redis_client', lambda: None)
    monkeypatch.setattr(market, '_shared_yahoo_client', lambda: object())
    monkeypatch.setattr(market, '_QUOTES_BATCH_DEADLINE_SECONDS', .1)
    before = time.monotonic()
    result = market.market_quotes_batch(market.MarketQuotesBatchIn(symbols=['MISSING']))
    after = time.monotonic()
    assert result == {'quotes': {'MISSING': None}}
    assert len(captured) == 1
    assert before + .1 <= captured[0] <= after + .1


def test_pool_never_queues_more_than_global_capacity_after_timeouts():
    pool = QuoteBatchPool(2)
    release = threading.Event()
    calls = []
    started = {symbol: threading.Event() for symbol in ['A', 'B']}

    def fetch(symbol):
        calls.append(symbol)
        started[symbol].set()
        assert release.wait(10), 'test did not release vendor'
        return {'c': 1}

    try:
        # Fill the pool explicitly, then wait for both vendors to enter.
        # The timeout contract must not depend on OS thread startup speed.
        for symbol in ['A', 'B']:
            pool.submit(symbol, fetch)
        assert all(event.wait(5) for event in started.values())
        assert pool.fetch(['A', 'B', 'C'], fetch, time.monotonic() + .03) == dict.fromkeys(['A', 'B', 'C'])
        assert pool.fetch(['D', 'E'], fetch, time.monotonic() + .03) == {'D': None, 'E': None}
        assert sorted(calls) == ['A', 'B']
        with pool.lock:
            assert len(pool.inflight) == 2
    finally:
        release.set()
        pool.close()


def test_fast_batch_drains_more_than_one_wave_and_handles_errors():
    pool = QuoteBatchPool(2)
    try:
        def fetch(symbol):
            if symbol == 'FAIL':
                raise RuntimeError('vendor')
            return {'c': len(symbol)}

        assert pool.fetch(['A', 'BB', 'CCC', 'FAIL'], fetch, time.monotonic() + 5) == {
            'A': {'c': 1}, 'BB': {'c': 2}, 'CCC': {'c': 3}, 'FAIL': None,
        }
        assert pool.fetch(['TOO-LATE'], fetch, time.monotonic() - 1) == {'TOO-LATE': None}
    finally:
        pool.close()


def test_fast_result_not_delayed_by_slow_peer():
    pool = QuoteBatchPool(2)
    release = threading.Event()
    try:
        def fetch(symbol):
            if symbol == 'SLOW':
                assert release.wait(10), 'test did not release vendor'
            return {'c': 1}

        out = pool.fetch(['FAST', 'SLOW'], fetch, time.monotonic() + 1)
        assert out == {'FAST': {'c': 1}, 'SLOW': None}
    finally:
        release.set()
        pool.close()
