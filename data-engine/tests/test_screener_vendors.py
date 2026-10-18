"""Hermetic tests: interchangeable screener quote/profile vendors (Finnhub ↔ Yahoo).

No network: all HTTP is faked. Covers the vendor Protocol registry, the
per-vendor normalization, the Finnhub default (unchanged behaviour) and the
unknown-vendor fallback.
"""

from __future__ import annotations

import threading

import pytest

from app.api.routes import screeners
from app.api.routes.screeners import (
    DEFAULT_SCREENER_VENDOR,
    SCREEN_VENDORS,
    FinnhubScreenVendor,
    YahooScreenVendor,
    _fetch_profile,
    _fetch_quote,
    resolve_screener_vendor,
)


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeClient:
    """Minimal httpx.Client stub: routes by URL substring."""

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


@pytest.fixture(autouse=True)
def _clean_caches():
    screeners._real_quote_cache.clear()
    screeners._real_profile_cache.clear()
    yield
    screeners._real_quote_cache.clear()
    screeners._real_profile_cache.clear()


def test_registry_has_both_vendors_and_finnhub_default():
    assert set(SCREEN_VENDORS) == {"finnhub", "yahoo"}
    assert DEFAULT_SCREENER_VENDOR == "finnhub"
    assert isinstance(SCREEN_VENDORS["finnhub"], FinnhubScreenVendor)
    assert isinstance(SCREEN_VENDORS["yahoo"], YahooScreenVendor)
    assert SCREEN_VENDORS["finnhub"].source_label == "finnhub_free"
    assert SCREEN_VENDORS["yahoo"].source_label == "yahoo_finance"


def test_profile_vendor_falls_back_to_finnhub_when_quotes_have_no_profiles(monkeypatch):
    """F63/F97: con SCREENER_QUOTE_VENDOR=yahoo los market caps salían 0 para
    siempre (Yahoo no tiene profile). El perfil debe pedirse a Finnhub cuando
    hay key; sin key se conserva el fallback honesto anterior."""
    from app.api.routes.screeners import resolve_profile_vendor

    class _Settings:
        finnhub_api_key = "k" * 8

    monkeypatch.setattr(screeners, "get_settings", lambda: _Settings())
    yahoo = resolve_screener_vendor("yahoo")
    assert yahoo.supports_profiles is False
    assert resolve_profile_vendor(yahoo).name == "finnhub"

    finnhub = resolve_screener_vendor("finnhub")
    assert finnhub.supports_profiles is True
    assert resolve_profile_vendor(finnhub).name == "finnhub"

    class _NoKey:
        finnhub_api_key = ""

    monkeypatch.setattr(screeners, "get_settings", lambda: _NoKey())
    assert resolve_profile_vendor(yahoo).name == "yahoo"


def test_gics_sector_normalizes_known_aliases_and_passes_unknown_through():
    from app.api.routes.screeners import _gics_sector

    assert _gics_sector("Technology") == "Information Technology"
    assert _gics_sector(" Financial Services ") == "Financials"  # tolera espacios
    assert _gics_sector("Financial Services") == "Financials"
    assert _gics_sector("Healthcare") == "Health Care"
    assert _gics_sector("Consumer Cyclical") == "Consumer Discretionary"
    assert _gics_sector("Consumer Defensive") == "Consumer Staples"
    assert _gics_sector("Basic Materials") == "Materials"
    assert _gics_sector("Health Care") == "Health Care"
    assert _gics_sector("Sector Inedito") == "Sector Inedito"
    assert _gics_sector(None) is None


def test_sector_filter_matches_gics_across_universe_db_and_profile(monkeypatch):
    """Conductual (F223): universo, fila de DB y perfil de Finnhub dicen todos
    'Technology'; el filtro por el GICS servido 'Information Technology' debe
    devolver las filas igualmente, y el item servido lleva el nombre GICS."""
    from app.api.routes.screeners import _gics_sector  # noqa: F401

    class _Settings:
        finnhub_api_key = "k" * 8
        screener_quote_vendor = "finnhub"

    monkeypatch.setattr(screeners, "get_settings", lambda: _Settings())
    # La DB enriquece MSFT con el alias historico 'Technology'
    monkeypatch.setattr(
        screeners,
        "_load_universe_from_db",
        lambda: {"MSFT": ("Microsoft", "Technology")},
    )
    monkeypatch.setattr(screeners, "_load_screener_ratios", lambda **kwargs: {})

    quote_client = _FakeClient(
        {"/quote": _FakeResponse({"c": 100.0, "d": 1.0, "dp": 1.0, "pc": 99.0, "v": 10, "t": 1})}
    )
    profile_client = _FakeClient(
        {
            "/stock/profile2": _FakeResponse(
                {
                    "ticker": "X",
                    "name": "X Co",
                    "marketCapitalization": 2.0,
                    "finnhubIndustry": "Technology",
                    "exchange": "NASDAQ",
                }
            )
        }
    )
    clients = [quote_client, profile_client]
    monkeypatch.setattr(screeners.httpx, "Client", lambda **kwargs: clients.pop(0))

    items = screeners._refetch_real_items(vendor="finnhub", tenant_id=None)
    assert items, "el universo falso debe producir items"
    assert all(item["sector"] == "Information Technology" for item in items), (
        "universe/DB/perfil 'Technology' se sirven ya normalizados a GICS"
    )
    # MSFT venia de la fila DB con 'Technology'; el resto del perfil Finnhub
    assert "MSFT" in {item["symbol"] for item in items}

    payload = screeners._real_response_payload(
        items, "finnhub", None, "Information Technology", 200
    )
    assert payload["count"] == len(items), (
        "filtrar por el GICS servido no puede dejar la tabla en cero (F223)"
    )
    # Un enlace legacy ?sector=Technology sigue funcionando tras normalizar
    legacy = screeners._real_response_payload(items, "finnhub", None, "Technology", 200)
    assert legacy["count"] == len(items)


def test_quote_client_never_leaks_finnhub_token_to_yahoo(monkeypatch):
    """Regresion de seguridad: con SCREENER_QUOTE_VENDOR=yahoo y key Finnhub
    (necesaria para perfiles), el cliente de la fase quotes NO puede fijar
    client.params={'token': key}: httpx 0.28 fusiona Client(params) con los
    params por request y la URL de quote a Yahoo llevaria ?token=SECRET."""
    import httpx as real_httpx

    class _Settings:
        finnhub_api_key = "k" * 8
        screener_quote_vendor = "yahoo"

    monkeypatch.setattr(screeners, "get_settings", lambda: _Settings())
    monkeypatch.setattr(screeners, "_load_universe_from_db", lambda: {})
    monkeypatch.setattr(screeners, "_load_screener_ratios", lambda **kwargs: {})

    quote_client = _FakeClient(
        {
            "chart": _FakeResponse(
                {
                    "chart": {
                        "result": [
                            {
                                "timestamp": [7],
                                "meta": {},
                                "indicators": {"quote": [{"close": [99.0], "volume": [3]}]},
                            }
                        ]
                    }
                }
            )
        }
    )
    profile_client = _FakeClient(
        {
            "/stock/profile2": _FakeResponse(
                {
                    "ticker": "X",
                    "name": "X Co",
                    "marketCapitalization": 2.0,
                    "finnhubIndustry": "Technology",
                    "exchange": "NASDAQ",
                }
            )
        }
    )
    clients = [quote_client, profile_client]
    test_thread = threading.get_ident()

    def _client_factory(**kwargs):
        # httpx.Client se parchea en el modulo global: un hilo de fondo ajeno a
        # este test (p. ej. un refresco del screener de otro test) que cree un
        # Client aqui consumiria los fakes y dejaba la lista vacia (flaky en
        # CI: IndexError). Solo el hilo del test recibe los fakes.
        if threading.get_ident() != test_thread:
            return _FakeClient({})
        return clients.pop(0)

    monkeypatch.setattr(screeners.httpx, "Client", _client_factory)

    items = screeners._refetch_real_items(vendor="yahoo", tenant_id=None)
    assert items, "Yahoo falso debe producir items"
    assert getattr(quote_client, "params", {}) == {}, (
        "la fase quotes NO puede llevar el token Finnhub (fuga a Yahoo)"
    )
    assert profile_client.params == {"token": "k" * 8}, (
        "la fase perfiles si lo lleva: va a Finnhub"
    )

    # Verificacion a nivel httpx real: con los params de la fase quotes,
    # la URL construida para Yahoo no lleva token.
    # (monkeypatch parchea el atributo en el modulo httpx global: hay que
    # deshacerlo antes de usar el Client real)
    monkeypatch.undo()
    with real_httpx.Client(params=getattr(quote_client, "params", {})) as real:
        req = real.build_request(
            "GET", "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"
        )
        assert "token" not in str(req.url).lower()


def test_resolve_vendor_falls_back_to_finnhub():
    assert resolve_screener_vendor(None).name == "finnhub"
    assert resolve_screener_vendor("").name == "finnhub"
    assert resolve_screener_vendor("no-such-vendor").name == "finnhub"
    assert resolve_screener_vendor("YAHOO").name == "yahoo"
    assert resolve_screener_vendor(" Finnhub ").name == "finnhub"


def test_finnhub_quote_normalization():
    client = _FakeClient(
        {"/quote": _FakeResponse({"c": 150.0, "d": 2.0, "dp": 1.35, "pc": 148.0, "v": 1000, "t": 123})}
    )
    quote = FinnhubScreenVendor().fetch_quote(client, "AAPL")
    assert quote == {
        "price": 150.0,
        "change": 2.0,
        "changePercent": 1.35,
        "volume": 1000.0,
        "prevClose": 148.0,
        "asOf": 123,
    }


def test_finnhub_quote_rejects_zero_price():
    client = _FakeClient({"/quote": _FakeResponse({"c": 0})})
    assert FinnhubScreenVendor().fetch_quote(client, "AAA") is None


def test_finnhub_profile_normalization():
    client = _FakeClient(
        {
            "/stock/profile2": _FakeResponse(
                {
                    "ticker": "AAPL",
                    "name": "Apple Inc",
                    "marketCapitalization": 3000.5,
                    "finnhubIndustry": "Technology",
                    "exchange": "NASDAQ",
                }
            )
        }
    )
    profile = FinnhubScreenVendor().fetch_profile(client, "AAPL")
    assert profile == {
        "name": "Apple Inc",
        "currency": None,
        "marketCap": pytest.approx(3000.5 * 1_000_000.0),
        "sector": "Technology",
        "exchange": "NASDAQ",
    }


def test_yahoo_quote_normalization():
    client = _FakeClient(
        {
            "chart": _FakeResponse(
                {
                    "chart": {
                        "result": [
                            {
                                "timestamp": [10, 20],
                                "meta": {"chartPreviousClose": 148.0},
                                "indicators": {
                                    "quote": [
                                        {"close": [148.0, 150.0], "volume": [900, 1000]}
                                    ]
                                },
                            }
                        ]
                    }
                }
            )
        }
    )
    quote = YahooScreenVendor().fetch_quote(client, "AAPL")
    assert quote["price"] == pytest.approx(150.0)
    assert quote["change"] == pytest.approx(2.0)
    assert quote["changePercent"] == pytest.approx(2.0 / 148.0 * 100)
    assert quote["volume"] == pytest.approx(1000.0)
    assert quote["prevClose"] == pytest.approx(148.0)
    assert quote["asOf"] == 20
    assert quote["asOfDate"] is None  # sin zona de mercado no se inventa fecha


def test_yahoo_quote_rejects_garbage():
    client = _FakeClient({"chart": _FakeResponse({"chart": {}})})
    assert YahooScreenVendor().fetch_quote(client, "AAPL") is None


def test_yahoo_has_no_profile():
    client = _FakeClient({})
    assert YahooScreenVendor().fetch_profile(client, "AAPL") is None


def test_fetch_wrappers_dispatch_per_vendor_with_isolated_caches():
    finnhub = _FakeClient(
        {"/quote": _FakeResponse({"c": 150.0, "d": 1.0, "dp": 0.5, "pc": 149.0, "v": 5, "t": 1})}
    )
    yahoo = _FakeClient(
        {
            "chart": _FakeResponse(
                {
                    "chart": {
                        "result": [
                            {
                                "timestamp": [7],
                                "meta": {},
                                "indicators": {"quote": [{"close": [99.0], "volume": [3]}]},
                            }
                        ]
                    }
                }
            )
        }
    )
    assert _fetch_quote(finnhub, "AAPL")["price"] == pytest.approx(150.0)  # default
    assert _fetch_quote(finnhub, "AAPL", vendor="finnhub")["price"] == pytest.approx(150.0)
    assert _fetch_quote(yahoo, "AAPL", vendor="yahoo")["price"] == pytest.approx(99.0)
    # Caches are namespaced per vendor, not shared.
    assert set(screeners._real_quote_cache) == {"finnhub:AAPL", "yahoo:AAPL"}
    # Profile: finnhub caches, yahoo (None) never caches.
    finnhub_profile = _FakeClient(
        {
            "/stock/profile2": _FakeResponse(
                {"ticker": "AAPL", "name": "Apple", "marketCapitalization": 1.0}
            )
        }
    )
    assert _fetch_profile(finnhub_profile, "AAPL")["name"] == "Apple"
    assert _fetch_profile(finnhub_profile, "AAPL", vendor="yahoo") is None
    assert set(screeners._real_profile_cache) == {"finnhub:AAPL"}


def test_yahoo_quote_time_matches_last_valid_close():
    client = _FakeClient({"chart": _FakeResponse({"chart": {"result": [{
        "timestamp": [10, 20, 30],
        "meta": {},
        "indicators": {"quote": [{"close": [148.0, 150.0, None]}]},
    }]}})})
    quote = YahooScreenVendor().fetch_quote(client, "AAPL")
    assert quote is not None
    assert quote["price"] == 150.0
    assert quote["asOf"] == 20


def test_yahoo_quote_dates_the_daily_candle_in_market_timezone():
    # 2026-10-16 13:30 UTC es la apertura de la vela diaria, no una hora de cotizacion.
    client = _FakeClient(
        {
            "chart": _FakeResponse(
                {
                    "chart": {
                        "result": [
                            {
                                "timestamp": [1792157400 - 86400, 1792157400],
                                "meta": {"exchangeTimezoneName": "America/New_York"},
                                "indicators": {"quote": [{"close": [148.0, 150.0], "volume": [900, 1000]}]},
                            }
                        ]
                    }
                }
            )
        }
    )
    quote = YahooScreenVendor().fetch_quote(client, "AAPL")
    assert quote["asOfDate"] == "2026-10-16"
