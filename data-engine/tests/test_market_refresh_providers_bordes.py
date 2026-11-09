"""market_refresh_service: bordes de los providers de precios/FX (sin DB).

Cubierto aqui:
- PublicPriceProvider._one / fetch: FMP devuelve precio 0 (falsy) y se cae al
  motivo sin proveedor; dos 429 concurrentes de FMP cuentan el breaker UNA
  vez (guard de transicion: el segundo ve al proveedor ya caido); Finnhub
  con precio 0 se salta; excepcion generica de Finnhub -> "Finnhub:<tipo>".
- fetch_intraday_yahoo: cierres todos NaN (dropna vacia) y frame sin columna
  Close -> el simbolo se omite sin romper el lote.
- YahooIntradayPriceProvider.fetch: simbolo que no mapea a ningun ticker se
  omite y la empresa queda con reason yahoo_sin_precio_intradia.
- ECBFXProvider.fetch: delega en ECBClient con los argumentos exactos.

Dobles declarados: clientes FMP/Finnhub falsos en la instancia (nunca red),
modulo yfinance falso via sys.modules con pandas real (nunca red), ECBClient
doblado a nivel de modulo, fetcher de Yahoo inyectado, cliente breaker falso
con espia de incr. La cache global _listing_currency_cache se sustituye por
un dict de scratch via monkeypatch (el original se restaura intacto).

NO cubierto a proposito: los cuerpos "..." de los Protocols PriceProvider y
FXProvider (129->exit, 135->exit) — son declaraciones de tipo, no codigo
ejecutable con sentido; y la orquestacion refresh() con DB (va en otra PR).
"""

import asyncio
import sys
import types
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
import pytest

import app.services.market_refresh_service as mrs
from app.models.entities import Company
from app.services.connectors.base import UpstreamRateLimited
from app.services.market_refresh_service import (
    ECBFXProvider,
    PublicPriceProvider,
    YahooIntradayPriceProvider,
    fetch_intraday_yahoo,
)


@pytest.fixture(autouse=True)
def _cache_listing_limpia(monkeypatch):
    # Dict de scratch: el original (con sus entradas previas) se restaura al
    # deshacer el monkeypatch; no se destruye con clear().
    monkeypatch.setattr(mrs, "_listing_currency_cache", {})


def _company(ticker: str = "AAPL") -> Company:
    return Company(
        ticker=ticker, name=f"{ticker} Inc.", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", cik="0000320193",
        company_type="holding", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )


class _FMP:
    def __init__(self, payload=None, exc=None, configured=True):
        self._payload = payload
        self._exc = exc
        self._configured = configured
        self.calls = 0

    def configured(self):
        return self._configured

    async def quote(self, ticker, max_retries=0):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._payload


class _Finnhub(_FMP):
    pass


def _provider(fmp=None, finnhub=None) -> PublicPriceProvider:
    provider = PublicPriceProvider(breaker_client=None)
    provider.fmp = fmp if fmp is not None else _FMP(configured=False)
    provider.finnhub = finnhub if finnhub is not None else _Finnhub(configured=False)
    return provider


@pytest.mark.anyio
async def test_fmp_precio_cero_no_es_dato_y_cae_al_motivo_final():
    provider = _provider(fmp=_FMP(payload=[{"price": 0, "timestamp": 1762560000}]))

    company, observation, error = await provider._one(_company(), date(2026, 11, 9))

    assert observation is None
    assert error == {"ticker": "AAPL", "reason": "no_price_provider_configured"}


@pytest.mark.anyio
async def test_dos_429_concurrentes_de_fmp_cuentan_el_breaker_una_vez():
    entradas = 0
    ambos_dentro = asyncio.Event()

    class _FMP429(_FMP):
        async def quote(self, ticker, max_retries=0):
            nonlocal entradas
            entradas += 1
            if entradas == 2:
                ambos_dentro.set()
            # Ambos 429 ya estaban en vuelo: el segundo no infla la racha.
            await asyncio.wait_for(ambos_dentro.wait(), timeout=5)
            raise UpstreamRateLimited("429 de prueba", retry_after=1.0)

    class _BreakerEspia:
        """Cliente breaker falso: cuenta las llamadas de registro (incr)."""

        def __init__(self):
            self.incr_calls = 0

        def get(self, key):
            return None

        def incr(self, key):
            self.incr_calls += 1
            return 1

        def expire(self, key, seconds):
            pass

        def set(self, key, value, ex=None):
            pass

        def delete(self, key):
            pass

    breaker = _BreakerEspia()
    fmp = _FMP429()
    provider = _provider(fmp=fmp)
    provider._breaker_client = breaker
    companies = [_company("AAPL"), _company("MSFT")]

    observations, errors = await provider.fetch(companies, as_of=date(2026, 11, 9))

    assert entradas == 2
    # Solo el PRIMER 429 registra en el breaker; el segundo ya ve al
    # proveedor caido y no infla la racha (espia, no solo _provider_down).
    assert breaker.incr_calls == 1
    assert observations == {}
    assert sorted(e["ticker"] for e in errors) == ["AAPL", "MSFT"]
    assert all(e["reason"] == "FMP:provider_unavailable" for e in errors)
    assert provider._provider_down == {"fmp"}


@pytest.mark.anyio
async def test_finnhub_precio_cero_se_salta():
    provider = _provider(finnhub=_Finnhub(payload={"c": 0, "t": 1762560000}))

    company, observation, error = await provider._one(_company(), date(2026, 11, 9))

    assert observation is None
    assert error == {"ticker": "AAPL", "reason": "no_price_provider_configured"}


@pytest.mark.anyio
async def test_finnhub_excepcion_generica_se_clasifica():
    provider = _provider(finnhub=_Finnhub(exc=RuntimeError("boom")))

    company, observation, error = await provider._one(_company(), date(2026, 11, 9))

    assert observation is None
    assert error == {"ticker": "AAPL", "reason": "Finnhub:RuntimeError"}


def _yf_falso(frame):
    class _TickerRoto:
        def __init__(self, symbol):
            self.fast_info = {}

    return types.SimpleNamespace(download=lambda *args, **kwargs: frame, Ticker=_TickerRoto)


def test_fetch_intraday_yahoo_cierres_vacios_se_omiten(monkeypatch):
    frame = pd.DataFrame(
        {"Close": [float("nan"), float("nan")]},
        index=pd.DatetimeIndex(
            [datetime(2026, 11, 9, 15, tzinfo=UTC), datetime(2026, 11, 9, 15, 15, tzinfo=UTC)]
        ),
    )
    monkeypatch.setitem(sys.modules, "yfinance", _yf_falso(frame))

    assert fetch_intraday_yahoo(["AAPL"]) == {}


def test_fetch_intraday_yahoo_sin_columna_close_se_omite(monkeypatch):
    frame = pd.DataFrame(
        {"Open": [1.0]},
        index=pd.DatetimeIndex([datetime(2026, 11, 9, 15, tzinfo=UTC)]),
    )
    monkeypatch.setitem(sys.modules, "yfinance", _yf_falso(frame))

    assert fetch_intraday_yahoo(["AAPL"]) == {}


@pytest.mark.anyio
async def test_yahoo_intraday_simbolo_sin_mapeo_se_omite():
    fetcher = lambda symbols: {"SIMBOLO_RARO": (Decimal("1"), date(2026, 11, 9))}
    provider = YahooIntradayPriceProvider(fetcher=fetcher)

    observations, errors = await provider.fetch([_company()], as_of=date(2026, 11, 9))

    assert observations == {}
    assert errors == [{"ticker": "AAPL", "reason": "yahoo_sin_precio_intradia"}]


@pytest.mark.anyio
async def test_ecb_fx_provider_delega_en_ecb_client(monkeypatch):
    capturado = {}
    centinela = object()

    class _ECB:
        async def conversion_rates(self, *, base_currency, quote_currencies):
            capturado["base"] = base_currency
            capturado["quotes"] = quote_currencies
            return centinela

    monkeypatch.setattr(mrs, "ECBClient", _ECB)

    resultado = await ECBFXProvider().fetch(
        base_currency="EUR", quote_currencies={"USD", "GBP"}
    )

    assert resultado is centinela
    assert capturado == {"base": "EUR", "quotes": {"USD", "GBP"}}
