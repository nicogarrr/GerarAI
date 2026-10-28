"""Veracidad del screener real (lista 13, puntos 3/4/5).

- Nada de ceros fabricados: campos ausentes en Finnhub/Yahoo -> None (nunca
  0.0 mostrado como "+0.00%" real) y marketCap None sin perfil (nunca 0.0).
- El as_of de la respuesta es el de la captura real de los datos; servir LKG
  stale no puede reescribirlo con time.time().

Hermetico: toda la red va falsificada; los caches se limpian por test.
"""

from __future__ import annotations

import pytest

from app.api.routes import screeners
from app.api.routes.screeners import FinnhubScreenVendor, YahooScreenVendor


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, routes: dict[str, _FakeResponse]) -> None:
        self._routes = routes
        self.calls: list[str] = []

    def get(self, url: str, **kwargs):
        self.calls.append(url)
        for marker, response in self._routes.items():
            if marker in url:
                return response
        return _FakeResponse({}, status_code=404)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeDb:
    def __init__(self, tenant_id=None) -> None:
        self.info = {"tenant_id": tenant_id}


@pytest.fixture(autouse=True)
def _clean_caches():
    for cache in (
        screeners._real_quote_cache,
        screeners._real_profile_cache,
        screeners._real_response_cache,
    ):
        cache.clear()
    screeners._real_items_cache.clear()
    screeners._real_refresh_futures.clear()
    screeners._real_refresh_generations.clear()
    screeners._real_refresh_last_attempt.clear()
    yield
    for cache in (
        screeners._real_quote_cache,
        screeners._real_profile_cache,
        screeners._real_response_cache,
    ):
        cache.clear()
    screeners._real_items_cache.clear()
    screeners._real_refresh_futures.clear()
    screeners._real_refresh_generations.clear()
    screeners._real_refresh_last_attempt.clear()


def test_empty_refresh_becomes_honest_unavailable_without_infinite_loading(monkeypatch):
    """Con el proveedor sin datos, el primer intento termina vacío; el request
    siguiente NO debe programar otro refresh (la UI vería 'Cargando' eterno):
    devuelve `refreshing=false` + `unavailable=true`."""

    class _Settings:
        finnhub_api_key = ""
        screener_quote_vendor = "offline"
        is_production = False

    monkeypatch.setattr(screeners, "get_settings", lambda: _Settings())
    monkeypatch.setattr(
        screeners, "_refetch_real_items", lambda **kwargs: []
    )

    first = screeners.real_time_screener(db=_FakeDb(tenant_id=7))
    future = screeners._real_refresh_futures[7]
    future.result(timeout=5)  # type: ignore[attr-defined]

    second = screeners.real_time_screener(db=_FakeDb(tenant_id=7))
    assert second["screener"] == []
    assert second["refreshing"] is False
    assert second["unavailable"] is True
    assert screeners._real_refresh_futures[7] is future


def test_finnhub_quote_missing_fields_are_none_not_zero():
    client = _FakeClient({"/quote": _FakeResponse({"c": 150.0, "t": 123})})
    quote = FinnhubScreenVendor().fetch_quote(client, "AAPL")
    assert quote is not None
    assert quote["price"] == 150.0
    assert quote["change"] is None
    assert quote["changePercent"] is None
    assert quote["volume"] is None
    assert quote["prevClose"] is None
    assert quote["asOf"] == 123


def test_finnhub_profile_without_market_cap_is_none_not_zero():
    client = _FakeClient(
        {"/stock/profile2": _FakeResponse({"ticker": "X", "name": "X Co"})}
    )
    profile = FinnhubScreenVendor().fetch_profile(client, "X")
    assert profile is not None
    assert profile["marketCap"] is None


def test_yahoo_quote_without_previous_close_has_no_change():
    client = _FakeClient(
        {
            "chart": _FakeResponse(
                {
                    "chart": {
                        "result": [
                            {
                                "timestamp": [7],
                                "meta": {},
                                "indicators": {"quote": [{"close": [99.0], "volume": []}]},
                            }
                        ]
                    }
                }
            )
        }
    )
    quote = YahooScreenVendor().fetch_quote(client, "AAPL")
    assert quote is not None
    assert quote["price"] == 99.0
    assert quote["change"] is None
    assert quote["changePercent"] is None
    assert quote["prevClose"] is None
    assert quote["volume"] is None


def test_refetch_items_market_cap_none_without_profile(monkeypatch):
    class _Settings:
        finnhub_api_key = "k" * 8
        screener_quote_vendor = "finnhub"

    monkeypatch.setattr(screeners, "get_settings", lambda: _Settings())
    monkeypatch.setattr(screeners, "_load_universe_from_db", lambda: {})
    monkeypatch.setattr(screeners, "_load_screener_ratios", lambda **kwargs: {})

    quote_client = _FakeClient(
        {"/quote": _FakeResponse({"c": 100.0, "d": 1.0, "dp": 1.0, "pc": 99.0, "v": 10, "t": 1})}
    )
    profile_client = _FakeClient({})  # 404: sin perfil para nadie
    clients = [quote_client, profile_client]
    monkeypatch.setattr(screeners.httpx, "Client", lambda **kwargs: clients.pop(0))

    items = screeners._refetch_real_items(vendor="finnhub", tenant_id=None)
    assert items, "el universo falso debe producir items"
    assert all(item["marketCap"] is None for item in items)

    payload = screeners._real_response_payload(items, "finnhub", None, None, 200)
    assert all(row["marketCap"] is None for row in payload["screener"])


def test_as_of_is_data_capture_time_not_serve_time(monkeypatch):
    # This test checks cache timestamps, not live background providers.
    monkeypatch.setattr(screeners, "_schedule_real_refresh", lambda *args, **kwargs: None)
    class _Settings:
        finnhub_api_key = ""
        screener_quote_vendor = "finnhub"

    monkeypatch.setattr(screeners, "get_settings", lambda: _Settings())

    items = [
        {
            "symbol": "AAA",
            "name": "AAA Co",
            "price": 10.0,
            "change": None,
            "changePercent": None,
            "marketCap": None,
            "volume": None,
            "prevClose": None,
            "sector": "Technology",
            "exchange": "US",
            "type": "Stock",
            "pe": None,
            "pb": None,
            "roe": None,
            "beta": None,
        }
    ]
    screeners._store_real_items(items, "finnhub", tenant_id=None)
    captured_at_wall = screeners._real_items_cache[None]["at_wall"]
    assert captured_at_wall > 0

    first = screeners.real_time_screener(db=_FakeDb())
    assert first["as_of"] == captured_at_wall, (
        "el as_of debe ser el de la captura de los datos, no el del servicio"
    )
    second = screeners.real_time_screener(db=_FakeDb())
    assert second["as_of"] == captured_at_wall, (
        "servir la respuesta cacheada no puede refrescar el as_of (LKG stale)"
    )


def test_as_of_reflects_oldest_carried_lkg_item():
    sym_a, sym_b = (row[0] for row in screeners._REAL_UNIVERSE[:2])
    first_items = [{"symbol": sym_a}, {"symbol": sym_b}]
    screeners._store_real_items(first_items, "finnhub", tenant_id=None)
    first_at_wall = screeners._real_items_cache[None]["at_wall"]

    # Segundo refresco: solo A llega fresco; B se conserva del LKG.
    screeners._store_real_items([{"symbol": sym_a}], "finnhub", tenant_id=None)
    bucket = screeners._real_items_cache[None]
    assert {item["symbol"] for item in bucket["items"]} == {sym_a, sym_b}
    assert bucket["at_wall"] == first_at_wall, (
        "con datos LKG mezclados, el as_of no puede afirmar la frescura del ultimo refresh"
    )


def test_finnhub_profile_currency_is_not_quote_currency():
    client = _FakeClient({"/stock/profile2": _FakeResponse({
        "ticker": "X", "name": "X Co", "currency": "EUR",
    })})
    profile = FinnhubScreenVendor().fetch_profile(client, "X")
    # profile2.currency is financial-statement currency, never a quote fallback.
    assert profile["currency"] == "EUR"
    import inspect

    from app.api.routes.screeners import _refetch_real_items
    assert '"currency": quote.get("currency"),' in inspect.getsource(_refetch_real_items)
    absent = _FakeClient({"/stock/profile2": _FakeResponse({"ticker": "X"})})
    assert FinnhubScreenVendor().fetch_profile(absent, "X")["currency"] is None
