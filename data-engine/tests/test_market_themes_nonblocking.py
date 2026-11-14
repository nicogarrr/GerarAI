"""La primera visita no espera al proveedor; frescura y reintentos honestos."""
import threading
import time

from app.api.routes import market
from app.services import market_themes as mt


def _wait(cache):
    deadline = time.monotonic() + 2
    while cache._refreshing and time.monotonic() < deadline:
        time.sleep(.001)
    assert not cache._refreshing


def test_cold_route_returns_while_compute_is_blocked_singleflight(monkeypatch):
    cache = mt.ThemesCache()
    entered, release = threading.Event(), threading.Event()
    calls = []
    def slow():
        calls.append(1)
        entered.set()
        release.wait(2)
        return dict(symbols_with_data=1, themes=[{"id": "real"}], status="ok", as_of="2026-11-13", generated_at="2026-11-14T10:00:00+00:00")
    monkeypatch.setattr(market, "_themes_cache", cache)
    monkeypatch.setattr(market, "_compute_themes_payload", slow)
    try:
        first = market.market_themes_ranking()
        assert entered.wait(1)
        assert not release.is_set()
        assert first["refreshing"] is True
        assert first["themes"] == [] and first["as_of"] is None
        assert first["generated_at"] is None  # no descarga que fechar todavía
        for _ in range(10):
            assert market.market_themes_ranking()["refreshing"] is True
        assert calls == [1]
    finally:
        release.set()
        _wait(cache)
    ready = market.market_themes_ranking()
    assert ready["themes"] == [{"id": "real"}]
    assert ready["refreshing"] is False and ready["stale"] is False
    assert ready["as_of"] == "2026-11-13"


def test_cold_failure_has_cooldown_then_recovers():
    clock = {"now": 0.0}
    cache = mt.ThemesCache(clock=lambda: clock["now"])
    calls = []
    def fail():
        calls.append(1)
        raise RuntimeError("proveedor no disponible")
    cache.get_background(fail)
    _wait(cache)
    failed = cache.get_background(fail)
    assert failed["refreshing"] is False and failed["themes"] == []
    assert calls == [1]
    clock["now"] = mt.FAILED_TTL_SECONDS + 1
    cache.get_background(lambda: dict(symbols_with_data=1, themes=[1], status="ok"))
    _wait(cache)
    assert cache.get_background(fail)["themes"] == [1]
    assert calls == [1]


def test_empty_result_cooldown_and_partial_stale_keeps_original_date():
    clock = {"now": 0.0}
    cache = mt.ThemesCache(clock=lambda: clock["now"])
    calls = []
    def empty():
        calls.append(1)
        return dict(symbols_with_data=0, themes=[], status="sin_datos", as_of=None)
    cache.get_background(empty)
    _wait(cache)
    assert cache.get_background(empty)["refreshing"] is False
    assert calls == [1]
    clock["now"] += mt.FAILED_TTL_SECONDS + 1
    original = dict(symbols_with_data=1, themes=[1], status="parcial", as_of="2026-11-13", intraday=True)
    cache.get_background(lambda: original)
    _wait(cache)
    clock["now"] += mt.PARTIAL_TTL_SECONDS + 1
    entered, release = threading.Event(), threading.Event()
    def slow_fail():
        entered.set()
        release.wait(2)
        raise ValueError("caído")
    try:
        stale = cache.get_background(slow_fail)
        assert entered.wait(1)
        assert stale["stale"] is True and stale["refreshing"] is True
        assert stale["as_of"] == original["as_of"] and stale["intraday"] is True
    finally:
        release.set()
        _wait(cache)
    assert cache._value is original


def test_prewarm_and_first_request_share_same_refresh(monkeypatch):
    cache = mt.ThemesCache()
    release, entered = threading.Event(), threading.Event()
    calls = []
    def slow():
        calls.append(1)
        entered.set()
        release.wait(2)
        return dict(symbols_with_data=0, themes=[], status="sin_datos")
    monkeypatch.setattr(market, "_themes_cache", cache)
    monkeypatch.setattr(market, "_compute_themes_payload", slow)
    try:
        market.start_themes_warmup()
        assert entered.wait(1)
        assert market.market_themes_ranking()["refreshing"] is True
        assert calls == [1]
    finally:
        release.set()
        _wait(cache)
