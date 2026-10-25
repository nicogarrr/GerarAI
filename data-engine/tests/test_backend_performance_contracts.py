"""Contratos de latencia para health readiness y screener real.

Las sondas y los clientes externos están simulados: estos tests no dependen de
Redis, Qdrant, MinIO ni de la red de Finnhub.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import main
from app.api.routes import screeners


def _fake_tenant_db(tenant_id: int = 1):
    """Sesion minima con contexto de tenant.

    El handler del screener real recibe `get_db`: los ratios que devuelve se
    derivan de `financial_facts`, que es TenantOwnedMixin, asi que la
    respuesta depende del tenant y por tanto de la sesion.
    """
    return SimpleNamespace(info={"tenant_id": tenant_id, "user_id": "user-1"})


def test_health_ready_times_out_dependencies_without_serial_wait(monkeypatch):
    """Dependencias caídas no pueden convertir /health/ready en una ruta lenta."""
    monkeypatch.setattr(main, "HEALTH_READY_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(main, "get_settings", lambda: object())

    def slow_optional_probe(_settings):
        time.sleep(0.20)
        return "ok"

    monkeypatch.setattr(main, "_probe_database", lambda _settings: "ok")
    monkeypatch.setattr(main, "_probe_llm", lambda _settings: "ok")
    monkeypatch.setattr(main, "_probe_redis", slow_optional_probe)
    monkeypatch.setattr(main, "_probe_qdrant", slow_optional_probe)
    monkeypatch.setattr(main, "_probe_minio", slow_optional_probe)

    started = time.perf_counter()
    response = asyncio.run(main.health_ready())
    elapsed = time.perf_counter() - started

    # El deadline de la sonda es 0,05 s y las tres sondas opcionales duermen
    # 0,20 s. Una implementacion SECUELA tardaria >=0,20 s; una concurrente,
    # ~0,05 s. El umbral de 0,15 s solo dejaba 1,33x de margen sobre el deadline
    # y hacia fallar el test con carga de maquina sin que hubiera una regresion.
    # 0,18 s sigue fallando una espera serial (0,20 s) y tolera el ruido.
    assert elapsed < 0.18, f"health_ready tardó {elapsed:.3f}s"
    payload = json.loads(response.body)
    assert response.status_code == 200, payload["checks"]
    assert payload["checks"] == {
        "database": "ok",
        "redis": "error:TimeoutError",
        "qdrant": "error:TimeoutError",
        "minio": "error:TimeoutError",
        "llm": "ok",
    }


def _screener_item(
    symbol: str,
    price: float,
    *,
    sector: str = "Technology",
    market_cap: float = 1_000_000.0,
) -> dict:
    return {
        "symbol": symbol,
        "name": symbol,
        "price": price,
        "change": 0.0,
        "changePercent": 0.0,
        "marketCap": market_cap,
        "volume": 1.0,
        "prevClose": price,
        "sector": sector,
        "exchange": "TEST",
        "type": "Stock",
        "pe": None,
        "pb": None,
        "roe": None,
        "beta": None,
    }


def test_real_screener_serves_lkg_and_refreshes_in_background(monkeypatch):
    """Un last-known-good vencido se responde sin esperar al proveedor."""
    old = _screener_item("AAPL", 10.0)
    new = _screener_item("AAPL", 11.0)
    started = threading.Event()
    release = threading.Event()

    def slow_refresh(**_kwargs):
        started.set()
        release.wait(1.0)
        return [new]

    monkeypatch.setattr(
        screeners,
        "_real_items_cache",
        {1: {"at": 0.0, "items": [old], "vendor": "finnhub"}},
    )
    monkeypatch.setattr(screeners, "_real_response_cache", {})
    monkeypatch.setattr(screeners, "_refetch_real_items", slow_refresh)
    monkeypatch.setattr(screeners, "get_settings", lambda: type(
        "FakeSettings",
        (),
        {"finnhub_api_key": "test-key", "screener_quote_vendor": "finnhub"},
    )())

    started_at = time.perf_counter()
    try:
        payload = screeners.real_time_screener(limit=1, db=_fake_tenant_db())
    finally:
        elapsed = time.perf_counter() - started_at

    assert elapsed < 0.10, f"LKG bloqueó durante {elapsed:.3f}s"
    assert payload["screener"][0]["price"] == 10.0
    assert started.wait(0.5), "el refresh no se programó en segundo plano"
    assert release.is_set() is False
    release.set()

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if screeners._real_items_cache[1]["items"][0]["price"] == 11.0:
            break
        time.sleep(0.01)
    assert screeners._real_items_cache[1]["items"][0]["price"] == 11.0


def test_real_response_cache_is_keyed_by_normalized_parameters(monkeypatch):
    """Cada combinación de filtros/limit obtiene su respuesta cacheada."""
    now = time.monotonic()
    items = [
        _screener_item("AAPL", 10.0, market_cap=2_000_000.0),
        _screener_item("MSFT", 20.0, market_cap=1_000_000.0),
    ]
    monkeypatch.setattr(
        screeners,
        "_real_items_cache",
        {1: {"at": now, "items": items, "vendor": "finnhub"}},
    )
    monkeypatch.setattr(screeners, "_real_response_cache", {})

    def unexpected_refresh(**_kwargs):
        raise AssertionError("una respuesta LKG fresca no debe refrescar")

    monkeypatch.setattr(screeners, "_refetch_real_items", unexpected_refresh)
    monkeypatch.setattr(screeners, "get_settings", lambda: type(
        "FakeSettings",
        (),
        {"finnhub_api_key": "test-key", "screener_quote_vendor": "finnhub"},
    )())

    first = screeners.real_time_screener(limit=1, sector="Technology", db=_fake_tenant_db())
    repeated = screeners.real_time_screener(limit=1, sector="technology", db=_fake_tenant_db())
    wider = screeners.real_time_screener(limit=2, sector="Technology", db=_fake_tenant_db())

    assert [row["symbol"] for row in first["screener"]] == ["AAPL"]
    assert repeated["screener"] == first["screener"]
    assert [row["symbol"] for row in wider["screener"]] == ["AAPL", "MSFT"]
    assert len(screeners._real_response_cache) == 2


def test_profile_phase_is_bounded_parallel_and_has_no_per_symbol_sleep(monkeypatch):
    """La fase profile2 debe compartir trabajo, no hacer un sleep por ticker."""
    symbols = [(f"T{index}", f"Ticker {index}", "Technology") for index in range(8)]
    profile_barrier = threading.Barrier(2, timeout=0.20)
    lock = threading.Lock()
    active = 0
    peak = 0
    sleep_calls: list[float] = []

    class FakeClient:
        params: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_quote(_client, symbol, *, vendor=None):
        return {
            "price": 10.0,
            "change": 0.1,
            "changePercent": 1.0,
            "volume": 100.0,
            "prevClose": 9.9,
            "asOf": 1,
        }

    def fake_profile(_client, symbol, *, vendor=None):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            try:
                profile_barrier.wait()
            except threading.BrokenBarrierError:
                # La implementación secuencial intencionadamente no puede
                # superar este barrier; el test debe fallar por peak/sleep,
                # no por una excepción de la prueba.
                pass
        finally:
            with lock:
                active -= 1
        return {
            "name": f"Profile {symbol}",
            "marketCap": 1_000_000.0,
            "sector": "Technology",
            "exchange": "TEST",
        }

    monkeypatch.setattr(screeners, "_REAL_UNIVERSE", symbols)
    monkeypatch.setattr(screeners, "_load_universe_from_db", lambda: {})
    monkeypatch.setattr(screeners.httpx, "Client", lambda **_kwargs: FakeClient())
    monkeypatch.setattr(screeners, "_fetch_quote", fake_quote)
    monkeypatch.setattr(screeners, "_fetch_profile", fake_profile)
    monkeypatch.setattr(screeners.time, "sleep", sleep_calls.append)

    screeners._real_quote_cache.clear()
    screeners._real_profile_cache.clear()
    screeners._finnhub_call_times.clear()
    monkeypatch.setattr(screeners, "get_settings", lambda: type(
        "FakeSettings",
        (),
        {"finnhub_api_key": "test-key", "screener_quote_vendor": "finnhub"},
    )())
    items = screeners._refetch_real_items(vendor="finnhub")

    assert len(items) == len(symbols)
    assert peak >= 2, f"profiles fueron secuenciales (peak={peak})"
    assert peak <= screeners.PROFILE_MAX_WORKERS
    assert sleep_calls == [], f"se mantienen sleeps por ticker: {sleep_calls}"
    assert not any("0.3" in str(value) for value in sleep_calls)


def test_market_indices_fetches_independent_symbols_in_parallel(monkeypatch):
    """Las cinco consultas Yahoo no forman un waterfall de cinco timeouts."""
    from app.api.routes import market

    symbols = [f"IDX{index}" for index in range(4)]
    barrier = threading.Barrier(2, timeout=0.20)
    lock = threading.Lock()
    active = 0
    peak = 0

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_fetch(_client, symbol):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
            return {
                "price": 100.0,
                "change": 1.0,
                "changePercent": 1.0,
            }
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(
        market, "_INDEXES", [{"symbol": symbol, "name": symbol} for symbol in symbols]
    )
    monkeypatch.setattr(market, "_cache", {"at": 0.0, "items": [], "fetched_at": None})
    monkeypatch.setattr(market.httpx, "Client", FakeClient)
    monkeypatch.setattr(market, "_fetch_index", fake_fetch)

    result = market.market_indices()

    assert [item["symbol"] for item in result["indices"]] == symbols
    assert peak >= 2, f"indices se consultaron secuencialmente (peak={peak})"
    assert peak <= 5


def test_real_response_cache_is_bounded(monkeypatch):
    """El cache por parámetros no crece indefinidamente con filtros arbitrarios."""
    now = time.monotonic()
    item = _screener_item("AAPL", 10.0)
    monkeypatch.setattr(
        screeners,
        "_real_items_cache",
        {1: {"at": now, "items": [item], "vendor": "finnhub"}},
    )
    monkeypatch.setattr(screeners, "_real_response_cache", {})
    monkeypatch.setattr(screeners, "_REAL_RESPONSE_CACHE_MAX", 2)
    monkeypatch.setattr(screeners, "_refetch_real_items", lambda **_kwargs: [item])
    monkeypatch.setattr(screeners, "get_settings", lambda: type(
        "FakeSettings",
        (),
        {"finnhub_api_key": "test-key", "screener_quote_vendor": "finnhub"},
    )())

    for sector in ("Technology", "Health Care", "Financials", "Industrials"):
        screeners.real_time_screener(limit=1, sector=sector, db=_fake_tenant_db())

    assert len(screeners._real_response_cache) <= 2
