"""Contratos de GET /api/market/quote/{symbol}: shape Finnhub vía Yahoo.

El endpoint revive el fallback del frontend para mercados no-US. Nunca
inventa datos: payload incompleto -> None -> 404 honesto.
"""

import httpx
import pytest
from fastapi import HTTPException

from app.api.routes import market


def _payload(closes=(100.0, 101.0, 102.5), opens=(99.0, 100.5, 101.0),
             highs=(101.0, 102.0, 103.0), lows=(98.0, 100.0, 101.0),
             previous_close=100.0):
    return {
        "chart": {
            "result": [
                {
                    "meta": {"chartPreviousClose": previous_close},
                    "indicators": {
                        "quote": [
                            {
                                "close": list(closes),
                                "open": list(opens),
                                "high": list(highs),
                                "low": list(lows),
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


def test_fetch_yahoo_quote_builds_finnhub_shape():
    client = _Client(resp=_Resp(200, _payload()))
    out = market._fetch_yahoo_quote(client, "SAN.MC")
    assert out == {
        "c": 102.5,
        "d": pytest.approx(1.5),
        "dp": pytest.approx(1.5 / 101.0 * 100),
        "h": 103.0,
        "l": 101.0,
        "o": 101.0,
        "pc": 101.0,
        "live_c": None,
        "live_t": None,
        "currency": None,
        "ct": None,  # sin timestamps en el payload: null honesto, no inventado
        "cd": None,
    }


def test_fetch_yahoo_quote_single_close_uses_meta_previous():
    client = _Client(resp=_Resp(200, _payload(closes=(105.0,), previous_close=100.0)))
    out = market._fetch_yahoo_quote(client, "ITX.MC")
    assert out is not None
    assert out["c"] == 105.0
    assert out["pc"] == 100.0


def test_fetch_yahoo_quote_empty_closes_returns_none():
    client = _Client(resp=_Resp(200, _payload(closes=(None, None))))
    assert market._fetch_yahoo_quote(client, "FAKE") is None


def test_fetch_yahoo_quote_http_error_returns_none():
    client = _Client(exc=httpx.ConnectError("down"))
    assert market._fetch_yahoo_quote(client, "AAPL") is None


def test_fetch_yahoo_quote_non_200_returns_none():
    client = _Client(resp=_Resp(429, {}))
    assert market._fetch_yahoo_quote(client, "AAPL") is None


def test_market_quote_404_when_no_data(monkeypatch):
    monkeypatch.setattr(market, "_fetch_yahoo_quote", lambda client, symbol: None)
    with pytest.raises(HTTPException) as exc:
        market.market_quote("NOEXISTE")
    assert exc.value.status_code == 404


def test_market_quote_caches_result(monkeypatch):
    calls = []

    def fake_fetch(client, symbol):
        calls.append(symbol)
        return {"c": 1.0, "d": 0.0, "dp": 0.0, "h": 1.0, "l": 1.0, "o": 1.0, "pc": 1.0}

    monkeypatch.setattr(market, "_fetch_yahoo_quote", fake_fetch)
    ticker = "CACHE-TEST-XYZ"
    market._quote_cache.pop(ticker, None)
    first = market.market_quote(ticker)
    second = market.market_quote(ticker)
    assert first == second
    assert calls == [ticker]


class _RecordingClient:
    def __init__(self, resp):
        self._resp = resp
        self.urls: list[str] = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self._resp


def test_yahoo_chart_symbol_maps_us_share_class_dot_to_dash():
    # Yahoo nombra las clases US con guion: BRK.B -> BRK-B (verificado contra
    # la chart API: BRK-B devuelve datos, BRK.B 404).
    assert market._yahoo_chart_symbol("BRK.B") == "BRK-B"
    assert market._yahoo_chart_symbol("BF.A") == "BF-A"


def test_yahoo_chart_symbol_keeps_exchange_suffixes_and_plain_tickers():
    # Sufijos de bolsa (dos letras) y tickers pelados no se tocan.
    assert market._yahoo_chart_symbol("TEF.MC") == "TEF.MC"
    assert market._yahoo_chart_symbol("ASML.AS") == "ASML.AS"
    assert market._yahoo_chart_symbol("AAPL") == "AAPL"


def test_quote_requests_dashed_symbol_for_share_class():
    client = _RecordingClient(_Resp(200, _payload()))
    out = market._fetch_yahoo_quote(client, "BRK.B")
    assert out is not None
    assert client.urls == [f"{market._YAHOO_CHART_URL}/BRK-B"]


def _payload_con_velas(closes, timestamps, tz="Europe/Madrid"):
    payload = _payload(closes=closes)
    result = payload["chart"]["result"][0]
    result["timestamp"] = list(timestamps)
    result["meta"]["exchangeTimezoneName"] = tz
    return payload


def test_fetch_yahoo_quote_devuelve_fecha_de_la_vela_del_cierre():
    # 2026-09-28 09:00 UTC y 2026-09-29 09:00 UTC: la fecha publicada es la
    # de la vela del ultimo cierre NO NULO, no la del ultimo timestamp.
    payload = _payload_con_velas(
        closes=(100.0, 102.5, None),
        timestamps=(1790586000, 1790672400, 1790758800),
    )
    out = market._fetch_yahoo_quote(_Client(resp=_Resp(200, payload)), "SAN.MC")
    assert out["c"] == 102.5
    assert out["ct"] == 1790672400
    assert out["cd"] == "2026-09-29"  # Europe/Madrid


def test_fetch_yahoo_quote_fecha_en_zona_del_mercado():
    # 2026-09-29 22:30 UTC = 2026-09-30 00:30 en Europe/Madrid, pero
    # 2026-09-29 en America/New_York: la fecha sigue al mercado.
    payload = _payload_con_velas(
        closes=(200.0,),
        timestamps=(1790721000,),
        tz="America/New_York",
    )
    out = market._fetch_yahoo_quote(_Client(resp=_Resp(200, payload)), "AAPL")
    assert out["cd"] == "2026-09-29"


def test_fetch_yahoo_quote_timestamps_cortos_no_rompen():
    payload = _payload_con_velas(closes=(100.0, 102.5), timestamps=(1790586000,))
    out = market._fetch_yahoo_quote(_Client(resp=_Resp(200, payload)), "SAN.MC")
    assert out["c"] == 102.5
    assert out["ct"] is None
    assert out["cd"] is None


def test_fetch_yahoo_quote_cd_fail_closed_sin_zona_valida():
    # 2026-09-29 23:30 UTC: en America/New_York seria 29, en Asia/Tokyo 30.
    # Sin zona valida NO se publica fecha (ct si, cd None): mejor sin fecha
    # que con la fecha del dia equivocado.
    for tz in (None, "Zona/Inventada"):
        payload = _payload_con_velas(closes=(200.0,), timestamps=(1790724600,), tz=tz)
        result = payload["chart"]["result"][0]
        if tz is None:
            result["meta"].pop("exchangeTimezoneName", None)
        out = market._fetch_yahoo_quote(_Client(resp=_Resp(200, payload)), "AAPL")
        assert out["c"] == 200.0
        assert out["ct"] == 1790724600
        assert out["cd"] is None


def test_spot_metadata_is_not_replaced_by_daily_candle():
    payload = _payload()
    result = payload["chart"]["result"][0]
    result["meta"].update({"regularMarketPrice": 103.25, "regularMarketTime": 1791460800, "currency": "USD"})
    quote = market._fetch_yahoo_quote(_Client(resp=_Resp(200, payload)), "AAPL")
    assert quote["c"] == 102.5
    assert quote["live_c"] == 103.25
    assert quote["live_t"] == 1791460800
    assert quote["currency"] == "USD"


def _session_payload(*, start, end, stamps, closes):
    return {"chart": {"result": [{
        "meta": {"chartPreviousClose": closes[0], "exchangeTimezoneName": "Europe/London",
                 "currentTradingPeriod": {"regular": {"start": start, "end": end}}},
        "timestamp": list(stamps),
        "indicators": {"quote": [{"close": list(closes), "open": list(closes),
                                  "high": list(closes), "low": list(closes)}]},
    }]}}


def _client_for(payload):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    return httpx.Client(transport=transport)


def test_open_session_bar_is_provisional_and_dropped(monkeypatch):
    """Sesion LSE abierta: la barra de hoy NO es un cierre. c/cd = ultimo cierre oficial."""
    start, end = 1792393200, 1792423800  # 19-oct-2026 07:00-15:30 UTC
    monkeypatch.setattr(market.time, "time", lambda: 1792410000)  # 11:00 UTC, en sesion
    payload = _session_payload(start=start, end=end, stamps=(1792047600, 1792134000, start),
                               closes=(4290.0, 4255.0, 4205.0))
    with _client_for(payload) as client:
        data = market._fetch_yahoo_quote(client, "CGEO.L")
    assert data["c"] == 4255.0 and data["pc"] == 4290.0
    assert data["cd"] == "2026-10-16"


def test_closed_session_bar_is_kept(monkeypatch):
    start, end = 1792393200, 1792423800
    monkeypatch.setattr(market.time, "time", lambda: end + 600)  # tras el cierre
    payload = _session_payload(start=start, end=end, stamps=(1792047600, 1792134000, start),
                               closes=(4290.0, 4255.0, 4220.0))
    with _client_for(payload) as client:
        data = market._fetch_yahoo_quote(client, "CGEO.L")
    assert data["c"] == 4220.0 and data["cd"] == "2026-10-19"


def test_bar_in_open_session_needs_all_fields():
    assert market._bar_in_open_session({}, 100) is False
    assert market._bar_in_open_session({"currentTradingPeriod": {"regular": {"start": 1, "end": 10}}}, None, now_ts=5) is False


def _single_candle_payload(previous_close=None):
    meta = {} if previous_close is None else {"chartPreviousClose": previous_close}
    return {"chart": {"result": [{"meta": meta, "timestamp": [1699900000],
            "indicators": {"quote": [{"close": [10.0], "open": [9.8], "high": [10.5], "low": [9.5]}]}}]}}


def test_quote_without_real_previous_close_has_no_invented_change():
    out = market._fetch_yahoo_quote(_Client(resp=_Resp(200, _single_candle_payload())), "NEW")
    assert out["c"] == 10.0
    assert out["pc"] is None and out["d"] is None and out["dp"] is None


def test_quote_uses_chart_previous_close_when_single_candle():
    out = market._fetch_yahoo_quote(_Client(resp=_Resp(200, _single_candle_payload(8.0))), "NEW")
    assert out["pc"] == 8.0 and out["d"] == pytest.approx(2.0) and out["dp"] == pytest.approx(25.0)


def test_quote_missing_ohlc_is_none_not_filled_with_close():
    payload = {"chart": {"result": [{"meta": {}, "timestamp": [1699800000, 1699900000],
               "indicators": {"quote": [{"close": [9.0, 10.0], "open": [8.8, None],
                                         "high": [9.5, None], "low": [8.5, None]}]}}]}}
    out = market._fetch_yahoo_quote(_Client(resp=_Resp(200, payload)), "X")
    assert out["c"] == 10.0 and out["pc"] == 9.0 and out["dp"] == pytest.approx(11.111, rel=1e-3)
    assert out["h"] is None and out["l"] is None and out["o"] is None


def _after_close_payload(rmt, close_today=None):
    # sesion regular 13:30-20:00 UTC (EDT); hoy = 1793107800
    meta = {"chartPreviousClose": 339.5, "regularMarketPrice": 347.1, "regularMarketTime": rmt,
            "exchangeTimezoneName": "America/New_York",
            "currentTradingPeriod": {"regular": {"start": 1793107800, "end": 1793131200}}}
    return {"chart": {"result": [{"meta": meta, "timestamp": [1793021400, 1793107800],
            "indicators": {"quote": [{"close": [343.91, close_today], "open": [344.0, None],
                                      "high": [345.0, None], "low": [343.0, None]}]}}]}}


def test_after_close_today_bar_without_close_uses_provider_final_price():
    out = market._fetch_yahoo_quote(_Client(resp=_Resp(200, _after_close_payload(1793131201))), "AAPL")
    assert out["c"] == 347.1 and out["pc"] == 343.91 and out["cd"] == "2026-10-27"


def test_during_session_today_bar_still_discarded():
    out = market._fetch_yahoo_quote(_Client(resp=_Resp(200, _after_close_payload(1793120000))), "AAPL")
    assert out["c"] == 343.91 and out["cd"] == "2026-10-26"
