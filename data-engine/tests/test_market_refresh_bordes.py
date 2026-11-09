"""Bordes de market_refresh_service: breaker redis, divisa de listado yahoo,
fetch intradia con yfinance falso y guard de tenant en refresh.

Dobles declarados: el cliente redis es un dict con contadores (no se prueba
Redis real); yfinance es un modulo falso con download/Ticker (no hay red);
la cache de divisa (_listing_currency_cache) se sustituye entera con
monkeypatch.setattr por test (es estado global de produccion que la
funcion modifica). pandas es real: el DataFrame sintetico ejerce el
MultiIndex de verdad.

NO se prueba: FMP/Finnhub reales (red), el refresco FX oficial BCE ni las
rutas. refresh() solo se ejerce hasta el guard de tenant (ValueError
inmediato): las corridas completas ya las cubren test_market_refresh*.py.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.market_refresh_service as mrs
from app.models.entities import Base


def test_breaker_client_none_sin_url(monkeypatch):
    monkeypatch.setattr(
        mrs, "get_settings", lambda: SimpleNamespace(redis_url=None)
    )
    assert mrs._marketdata_breaker_client() is None


def test_breaker_client_none_si_redis_falla(monkeypatch):
    class RedisRoto:
        @staticmethod
        def from_url(*args, **kwargs):
            raise OSError("sin redis")

    monkeypatch.setitem(sys.modules, "redis", RedisRoto)
    monkeypatch.setattr(
        mrs, "get_settings", lambda: SimpleNamespace(redis_url="redis://x")
    )
    assert mrs._marketdata_breaker_client() is None


def test_breaker_client_ok_devuelve_cliente(monkeypatch):
    creado = SimpleNamespace(ping=lambda: True)

    class RedisFalso:
        @staticmethod
        def from_url(url, **kwargs):
            assert url == "redis://x"
            return creado

    monkeypatch.setitem(sys.modules, "redis", RedisFalso)
    monkeypatch.setattr(
        mrs, "get_settings", lambda: SimpleNamespace(redis_url="redis://x")
    )
    assert mrs._marketdata_breaker_client() is creado


class _RedisDict:
    """Doble declarado de redis: claves en un dict, llamadas registradas."""

    def __init__(self):
        self.data = {}
        self.expiraciones = []
        self.fallo = False

    def get(self, key):
        if self.fallo:
            raise OSError("caido")
        return self.data.get(key)

    def incr(self, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    def expire(self, key, segundos):
        self.expiraciones.append((key, segundos))

    def set(self, key, valor, ex=None):
        self.data[key] = valor

    def delete(self, key):
        self.data.pop(key, None)


def test_breaker_open_sin_cliente_y_con_fallo():
    assert mrs._marketdata_breaker_open(None, "fmp") is False
    caido = _RedisDict()
    caido.fallo = True
    assert mrs._marketdata_breaker_open(caido, "fmp") is False  # fail-open


def test_breaker_record_429_abre_a_la_racha_limite():
    client = _RedisDict()
    for _ in range(mrs._MARKETDATA_BREAKER_STREAK_LIMIT - 1):
        mrs._marketdata_breaker_record_429(client, "fmp")
        assert mrs._marketdata_breaker_open(client, "fmp") is False
    assert client.expiraciones[0][0] == "marketdata_breaker:fmp:429_streak"
    mrs._marketdata_breaker_record_429(client, "fmp")
    assert client.data["marketdata_breaker:fmp:open"] == "1"
    assert "marketdata_breaker:fmp:429_streak" not in client.data
    assert mrs._marketdata_breaker_open(client, "fmp") is True


def test_breaker_record_429_traga_errores():
    caido = _RedisDict()
    caido.fallo = True
    mrs._marketdata_breaker_record_429(caido, "fmp")  # no lanza
    mrs._marketdata_breaker_record_429(None, "fmp")  # no-op


class _TickerFalso:
    def __init__(self, symbol):
        self.fast_info = {"currency": "GBp"}


@pytest.fixture
def cache_divisa(monkeypatch):
    monkeypatch.setattr(mrs, "_listing_currency_cache", {})
    return mrs._listing_currency_cache


def test_listing_currency_cachea_el_metadato(cache_divisa):
    llamadas = {"n": 0}

    class YF:
        @staticmethod
        def Ticker(symbol):
            llamadas["n"] += 1
            return _TickerFalso(symbol)

    assert mrs._listing_currency(YF, "AAA") == "GBp"
    assert mrs._listing_currency(YF, "AAA") == "GBp"
    assert llamadas["n"] == 1  # la segunda sale de la cache


def test_listing_currency_expira_a_las_24h(cache_divisa):
    yf_viejo = SimpleNamespace()
    cache_divisa["AAA"] = (
        time.monotonic() - mrs._LISTING_CURRENCY_TTL_S - 1,
        yf_viejo,
        "EUR",
    )
    assert mrs._listing_currency(SimpleNamespace(Ticker=_TickerFalso), "AAA") == "GBp"


def test_listing_currency_otro_modulo_no_reusa_la_entrada(cache_divisa):
    yf_otro = SimpleNamespace()
    cache_divisa["AAA"] = (time.monotonic(), yf_otro, "EUR")
    assert mrs._listing_currency(SimpleNamespace(Ticker=_TickerFalso), "AAA") == "GBp"


def test_listing_currency_fallo_no_se_recuerda(cache_divisa):
    class YFRoto:
        @staticmethod
        def Ticker(symbol):
            raise OSError("sin red")

    assert mrs._listing_currency(YFRoto, "AAA") is None
    assert cache_divisa == {}


class _YFDescarga:
    """yfinance falso: download devuelve un DataFrame MultiIndex real."""

    def __init__(self, frame):
        self._frame = frame

    def download(self, *args, **kwargs):
        return self._frame

    Ticker = staticmethod(_TickerFalso)


def _frame_intradia():
    import pandas as pd

    columnas = pd.MultiIndex.from_tuples([("AAA", "Close"), ("BBB", "Close")])
    idx = pd.to_datetime(["2026-11-06 15:30", "2026-11-06 15:45"])
    return pd.DataFrame([[10.0, float("nan")], [10.25, 20.5]], index=idx, columns=columnas)


def test_fetch_intraday_yahoo_ok(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", _YFDescarga(_frame_intradia()))
    monkeypatch.setattr(mrs, "_listing_currency", lambda yf, s: "USD")
    out = mrs.fetch_intraday_yahoo(["AAA", "BBB"])
    assert out["AAA"] == (Decimal("10.25"), date(2026, 11, 6), "USD")
    assert out["BBB"] == (Decimal("20.5"), date(2026, 11, 6), "USD")


def test_fetch_intraday_yahoo_sin_simbolos_ni_frame(monkeypatch):
    assert mrs.fetch_intraday_yahoo([]) == {}
    import pandas as pd

    monkeypatch.setitem(sys.modules, "yfinance", _YFDescarga(pd.DataFrame()))
    assert mrs.fetch_intraday_yahoo(["AAA"]) == {}


def test_fetch_intraday_yahoo_columna_simple_y_valor_no_positivo(monkeypatch):
    import pandas as pd

    idx = pd.to_datetime(["2026-11-06 15:45"])
    frame = pd.DataFrame({"Close": [0.0]}, index=idx)  # un solo ticker, sin grupo
    monkeypatch.setitem(sys.modules, "yfinance", _YFDescarga(frame))
    monkeypatch.setattr(mrs, "_listing_currency", lambda yf, s: None)
    assert mrs.fetch_intraday_yahoo(["AAA"]) == {}  # 0 no es precio honesto


def test_refresh_exige_contexto_de_tenant():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:  # sin info["tenant_id"]
            servicio = mrs.MarketRefreshService(
                price_provider=SimpleNamespace(),
                fx_provider=SimpleNamespace(),
            )
            with pytest.raises(ValueError, match="Tenant context"):
                asyncio.run(servicio.refresh(db))
    finally:
        engine.dispose()
