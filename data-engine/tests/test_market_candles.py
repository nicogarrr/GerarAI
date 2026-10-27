"""Contratos de GET /api/market/candles/{symbol}: shape Finnhub vía Yahoo.

Finnhub free no sirve velas de mercados no-US; el gráfico de la ficha IBEX
depende de este fallback. Los huecos (close null) se descartan en todos los
arrays para mantener la alineación por índice.
"""

import httpx
import pytest
from fastapi import HTTPException

from app.api.routes import market


def _payload():
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [1000, 2000, 3000],
                    "indicators": {
                        "quote": [
                            {
                                "close": [10.0, None, 12.0],
                                "open": [9.5, 11.0, 11.5],
                                "high": [10.5, None, 12.5],
                                "low": [9.0, 10.5, 11.0],
                                "volume": [100, 200, 300],
                            }
                        ]
                    },
                }
            ]
        }
    }


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Client:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc

    def get(self, *args, **kwargs):
        if self._exc:
            raise self._exc
        return self._resp


def test_candles_drop_null_closes_everywhere_aligned():
    out = market._fetch_yahoo_candles(_Client(resp=_Resp(200, _payload())), "SAN.MC", 0, 9999, "1d")
    assert out is not None
    assert out["s"] == "ok"
    assert out["t"] == [1000, 3000]
    assert out["c"] == [10.0, 12.0]
    assert out["o"] == [9.5, 11.5]
    assert out["h"] == [10.5, 12.5]
    assert out["l"] == [9.0, 11.0]
    assert out["v"] == [100.0, 300.0]


def test_candles_null_ohlc_stays_unknown():
    payload = _payload()
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    quote["open"] = [None, None, None]
    out = market._fetch_yahoo_candles(_Client(resp=_Resp(200, payload)), "SAN.MC", 0, 9999, "1d")
    assert out is not None
    assert out["o"] == [None, None]


def test_candles_all_null_returns_none():
    payload = _payload()
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [None, None, None]
    assert market._fetch_yahoo_candles(_Client(resp=_Resp(200, payload)), "X", 0, 9999, "1d") is None


def test_candles_http_error_returns_none():
    assert market._fetch_yahoo_candles(_Client(exc=httpx.ConnectError("down")), "X", 0, 9999, "1d") is None


def test_route_404_when_no_data(monkeypatch):
    monkeypatch.setattr(market, "_fetch_yahoo_candles", lambda *a: None)
    with pytest.raises(HTTPException) as exc:
        market.market_candles("NOEXISTE", from_ts=0, to_ts=9999)
    assert exc.value.status_code == 404


def test_route_rejects_inverted_range():
    with pytest.raises(HTTPException):
        market.market_candles("SAN.MC", from_ts=9999, to_ts=1000)


def test_route_caches(monkeypatch):
    calls = []

    def fake_fetch(client, symbol, from_ts, to_ts, interval):
        calls.append(symbol)
        return {"s": "ok", "c": [1.0], "t": [1], "o": [1.0], "h": [1.0], "l": [1.0], "v": [0.0]}

    monkeypatch.setattr(market, "_fetch_yahoo_candles", fake_fetch)
    ticker = "CANDLE-CACHE-XYZ"
    market._candles_cache.clear()
    first = market.market_candles(ticker, from_ts=0, to_ts=9999)
    second = market.market_candles(ticker, from_ts=0, to_ts=9999)
    assert first == second
    assert calls == [ticker]


class _RecordingClient:
    def __init__(self, resp):
        self._resp = resp
        self.urls: list[str] = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self._resp


def test_candles_request_dashed_symbol_for_share_class():
    # Sin la traduccion BRK.B -> BRK-B, Yahoo da 404 y el historial de la
    # ficha sale vacio (F161: chip «parcial» sin serie que mostrar).
    client = _RecordingClient(_Resp(200, _payload()))
    out = market._fetch_yahoo_candles(client, "BRK.B", 0, 9999, "1d")
    assert out is not None
    assert client.urls == [f"{market._YAHOO_CHART_URL}/BRK-B"]


@pytest.mark.parametrize("shape", ["null", "absent", "short"])
def test_yahoo_close_only_keeps_prices_but_never_fabricates_ohlc(shape):
    payload = _payload()
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    for key in ("open", "high", "low", "volume"):
        if shape == "absent":
            quote.pop(key)
        else:
            quote[key] = [None, None, None] if shape == "null" else [None]
    out = market._fetch_yahoo_candles(_Client(resp=_Resp(200, payload)), "HIMS", 0, 9999, "1d")
    assert out is not None
    assert out["c"] == [10, 12]
    assert out["t"] == [1000, 3000]
    for key in ("o", "h", "l", "v"):
        assert out[key] == [None, None]


def test_optional_ohlc_fields_are_independently_preserved():
    payload = _payload()
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    quote["open"] = [None, None, 11.5]
    quote["high"] = [10.5, None, None]
    quote["low"] = [9, None, float("nan")]
    out = market._fetch_yahoo_candles(_Client(resp=_Resp(200, payload)), "HIMS", 0, 9999, "1d")
    assert out is not None
    assert out["o"] == [None, 11.5]
    assert out["h"] == [10.5, None]
    assert out["l"] == [9, None]


def test_candles_carry_currency_declared_in_same_yahoo_response():
    payload = _payload()
    payload["chart"]["result"][0]["meta"] = {"currency": "GBp"}
    out = market._fetch_yahoo_candles(_Client(resp=_Resp(200, payload)), "CGEO.L", 0, 9999, "1d")
    assert out is not None and out["currency"] == "GBp"


def test_candles_without_meta_currency_have_no_currency_key():
    out = market._fetch_yahoo_candles(_Client(resp=_Resp(200, _payload())), "SAN.MC", 0, 9999, "1d")
    assert out is not None and "currency" not in out
