"""Contratos de POST /api/market/quotes/batch: cotizaciones por lote.

El sondeo de oportunidades del Inicio pedia cotizacion por candidata (N x
fetch desde Vercel con cache en memoria de 45s por instancia serverless).
El lote la sirve desde el backend con cache Redis compartida de 60s (misma
frescura que la cache en memoria del endpoint individual): una llamada por
carga en vez de N, y misses compartidos entre usuarios y workers.

Nunca inventa datos: simbolo sin cotizacion -> null en su entrada, no error
global. Redis caido -> fail-open al fetch directo.
"""

import json

import pytest
from fastapi import HTTPException

from app.api.routes import market


class FakeRedis:
    def __init__(self, values=None, exc=None):
        self.values = dict(values or {})
        self.exc = exc
        self.setex_calls = []

    def get(self, key):
        if self.exc:
            raise self.exc
        return self.values.get(key)

    def setex(self, key, ttl, value):
        if self.exc:
            raise self.exc
        self.setex_calls.append((key, ttl, value))
        self.values[key] = value


QUOTE_SAN = {"c": 102.5, "pc": 100.0, "currency": "EUR"}
QUOTE_AAPL = {"c": 250.1, "pc": 248.0, "currency": "USD"}


@pytest.fixture
def clean_memory_cache():
    market._quote_cache.clear()
    yield
    market._quote_cache.clear()


def _fake_fetch(payloads):
    calls = []

    def fetch(client, symbol):
        calls.append(symbol)
        return payloads.get(symbol)

    return fetch, calls


def test_batch_hits_redis_without_fetching(monkeypatch, clean_memory_cache):
    redis = FakeRedis({
        market._quote_redis_key("SAN.MC"): json.dumps(QUOTE_SAN),
        market._quote_redis_key("AAPL"): json.dumps(QUOTE_AAPL),
    })
    monkeypatch.setattr(market, "_batch_redis_client", lambda: redis)
    fetch, calls = _fake_fetch({})
    monkeypatch.setattr(market, "_fetch_yahoo_quote", fetch)

    out = market.market_quotes_batch(market.MarketQuotesBatchIn(symbols=["SAN.MC", "AAPL"]))

    assert out == {"quotes": {"SAN.MC": QUOTE_SAN, "AAPL": QUOTE_AAPL}}
    assert calls == []


def test_batch_miss_fetches_once_and_caches_redis_and_memory(monkeypatch, clean_memory_cache):
    redis = FakeRedis()
    monkeypatch.setattr(market, "_batch_redis_client", lambda: redis)
    fetch, calls = _fake_fetch({"SAN.MC": QUOTE_SAN})
    monkeypatch.setattr(market, "_fetch_yahoo_quote", fetch)

    out = market.market_quotes_batch(market.MarketQuotesBatchIn(symbols=["san.mc", "MISSING"]))

    assert out["quotes"]["SAN.MC"] == QUOTE_SAN
    assert out["quotes"]["MISSING"] is None
    assert sorted(calls) == ["MISSING", "SAN.MC"]
    # Redis: clave con prefijo estable y TTL igual a la frescura del single (60s).
    assert redis.setex_calls == [
        (market._quote_redis_key("SAN.MC"), 60, json.dumps(QUOTE_SAN))
    ]
    # Memoria del single reutilizada: una segunda llamada no refetchea.
    out2 = market.market_quotes_batch(market.MarketQuotesBatchIn(symbols=["SAN.MC"]))
    assert out2["quotes"]["SAN.MC"] == QUOTE_SAN
    assert sorted(calls) == ["MISSING", "SAN.MC"]


def test_batch_fail_open_when_redis_down(monkeypatch, clean_memory_cache):
    monkeypatch.setattr(market, "_batch_redis_client", lambda: None)
    fetch, calls = _fake_fetch({"AAPL": QUOTE_AAPL})
    monkeypatch.setattr(market, "_fetch_yahoo_quote", fetch)

    out = market.market_quotes_batch(market.MarketQuotesBatchIn(symbols=["AAPL"]))

    assert out["quotes"]["AAPL"] == QUOTE_AAPL
    assert calls == ["AAPL"]


def test_batch_redis_error_still_fetches(monkeypatch, clean_memory_cache):
    redis = FakeRedis(exc=RuntimeError("redis caido"))
    monkeypatch.setattr(market, "_batch_redis_client", lambda: redis)
    fetch, calls = _fake_fetch({"AAPL": QUOTE_AAPL})
    monkeypatch.setattr(market, "_fetch_yahoo_quote", fetch)

    out = market.market_quotes_batch(market.MarketQuotesBatchIn(symbols=["AAPL"]))

    assert out["quotes"]["AAPL"] == QUOTE_AAPL
    assert calls == ["AAPL"]


def test_batch_rejects_more_than_30_symbols(clean_memory_cache):
    with pytest.raises(HTTPException) as excinfo:
        market.market_quotes_batch(
            market.MarketQuotesBatchIn(symbols=[f"S{i}" for i in range(31)])
        )
    assert excinfo.value.status_code == 400


def test_batch_filters_invalid_symbols_without_fetching(monkeypatch, clean_memory_cache):
    monkeypatch.setattr(market, "_batch_redis_client", lambda: None)
    fetch, calls = _fake_fetch({})
    monkeypatch.setattr(market, "_fetch_yahoo_quote", fetch)

    # Misma regla que el single: controles no imprimibles, vacios y >32 chars.
    out = market.market_quotes_batch(
        market.MarketQuotesBatchIn(symbols=["SA\x00N.MC", "  ", "X" * 33])
    )

    assert out["quotes"] == {}
    assert calls == []
