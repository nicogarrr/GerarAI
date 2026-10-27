"""/quote y /candles reutilizan un único cliente HTTP con timeouts acotados."""

from __future__ import annotations

import httpx
import pytest

from app.api.routes import market


@pytest.fixture(autouse=True)
def _fresh_client():
    market.close_shared_yahoo_client()
    market._quote_cache.clear()
    market._candles_cache.clear()
    yield
    market.close_shared_yahoo_client()
    market._quote_cache.clear()
    market._candles_cache.clear()


def _record_clients(monkeypatch, name: str, value) -> list:
    seen: list = []

    def fake(client, *args):
        seen.append(client)
        return value

    monkeypatch.setattr(market, name, fake)
    return seen


def test_quote_cache_misses_reuse_one_client(monkeypatch):
    seen = _record_clients(monkeypatch, "_fetch_yahoo_quote", {"c": 1.0})
    for symbol in ("AAA", "BBB", "CCC"):  # tres fallos de caché
        market.market_quote(symbol)
    assert len(seen) == 3
    assert seen[0] is seen[1] is seen[2]
    assert not seen[0].is_closed  # antes se cerraba tras cada petición


def test_candles_share_the_quote_client(monkeypatch):
    quotes = _record_clients(monkeypatch, "_fetch_yahoo_quote", {"c": 1.0})
    market.market_quote("AAA")
    candles = _record_clients(monkeypatch, "_fetch_yahoo_candles", {"s": "ok"})
    market.market_candles("AAA", from_ts=0, to_ts=86400 * 10, resolution="D")
    market.market_candles("BBB", from_ts=0, to_ts=86400 * 10, resolution="D")
    assert candles[0] is candles[1] is quotes[0]


def test_client_has_bounded_timeouts_and_headers():
    client = market._shared_yahoo_client()
    assert client.timeout.connect == 5.0
    assert client.timeout.pool == 5.0
    assert client.timeout.read == 15.0
    assert client.headers["User-Agent"] == market._HEADERS["User-Agent"]


def test_closed_client_is_recreated():
    first = market._shared_yahoo_client()
    first.close()
    second = market._shared_yahoo_client()
    assert second is not first and not second.is_closed


def test_requests_send_connect_timeout(monkeypatch):
    """Cada petición fija connect=5 s: Yahoo caído no retiene un hilo 15-20 s en el handshake."""
    timeouts: list[httpx.Timeout] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"])
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert market._fetch_yahoo_quote(client, "AAA") is None
    assert market._fetch_yahoo_candles(client, "AAA", 0, 9999, "1d") is None
    assert [t["connect"] for t in timeouts] == [5.0, 5.0]
    assert [t["read"] for t in timeouts] == [15.0, 20.0]
