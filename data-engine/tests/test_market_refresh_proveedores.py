"""Caminos FMP/Finnhub de PublicPriceProvider con clientes falsos, y breaker
con valores exactos de TTL/ex (salvedad del auditor sobre el lote 1).

Dobles declarados: self.fmp / self.finnhub se sustituyen por SimpleNamespace
con configured() y quote() async (sin red, sin claves); las Company son
SimpleNamespace (el proveedor solo lee ticker/exchange/currency); el breaker
es un dict con contadores que registra los valores exactos de expire/set.

NO se prueba: FMP/Finnhub reales, el refresco FX ni la persistencia
(eso lo cubren test_market_refresh*.py). El test de timeout usa
PER_TICKER_TIMEOUT_SECONDS=0.01 contra una corutina de 5 s: el timeout
dispara siempre, no es una medicion de rendimiento con reloj real.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import app.services.market_refresh_service as mrs
from app.services.connectors.base import UpstreamRateLimited

AS_OF = date(2026, 11, 7)
TS_QUOTE = int(datetime(2026, 11, 6, 21, 0, tzinfo=UTC).timestamp())


def _empresa(ticker="AAPL", exchange="NASDAQ", currency="USD"):
    return SimpleNamespace(ticker=ticker, exchange=exchange, currency=currency)


def _cliente(configurado=True, quote=None):
    async def _sin_quote(*args, **kwargs):
        raise AssertionError("quote no deberia llamarse")

    return SimpleNamespace(
        configured=lambda: configurado,
        quote=quote or _sin_quote,
        llamadas=[],
    )


def _proveedor(fmp=None, finnhub=None, breaker=None):
    provider = mrs.PublicPriceProvider(breaker_client=breaker)
    provider.fmp = fmp or _cliente(configurado=False)
    provider.finnhub = finnhub or _cliente(configurado=False)
    return provider


def _corre(provider, companies):
    return asyncio.run(provider.fetch(companies, as_of=AS_OF))


class _BreakerDict:
    """Doble declarado de redis: registra valores exactos de expire/set."""

    def __init__(self):
        self.data = {}
        self.expiraciones = []
        self.sets = []

    def get(self, key):
        return self.data.get(key)

    def incr(self, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    def expire(self, key, segundos):
        self.expiraciones.append((key, segundos))

    def set(self, key, valor, ex=None):
        self.sets.append((key, valor, ex))
        self.data[key] = valor

    def delete(self, key):
        self.data.pop(key, None)


def test_breaker_valores_exactos_de_ttl_y_ex():
    breaker = _BreakerDict()
    for _ in range(mrs._MARKETDATA_BREAKER_STREAK_LIMIT):
        mrs._marketdata_breaker_record_429(breaker, "fmp")
    assert breaker.expiraciones == [
        ("marketdata_breaker:fmp:429_streak", int(mrs._MARKETDATA_BREAKER_WINDOW_S))
    ]
    assert breaker.sets == [
        (
            "marketdata_breaker:fmp:open",
            "1",
            int(mrs._MARKETDATA_BREAKER_COOLDOWN_S),
        )
    ]


def test_breaker_record_429_con_incr_caido_no_lanza():
    class IncrRoto(_BreakerDict):
        def incr(self, key):
            raise OSError("redis caido")

    mrs._marketdata_breaker_record_429(IncrRoto(), "fmp")  # fail-open


def test_no_us_devuelve_non_us_listing():
    observations, errors = _corre(_proveedor(), [_empresa("SAN", "BME", "EUR")])
    assert observations == {}
    assert errors == [{"ticker": "SAN", "reason": "non_us_listing"}]


def test_fmp_quote_ok_con_volumen():
    async def quote(ticker, max_retries=0):
        return [{"price": "273.5", "timestamp": TS_QUOTE, "volume": 12345}]

    fmp = _cliente(quote=quote)
    observations, errors = _corre(_proveedor(fmp=fmp), [_empresa()])
    obs = observations["AAPL"]
    assert (obs.price, obs.price_date, obs.source) == (
        Decimal("273.5"),
        date(2026, 11, 6),
        "FMP",
    )
    assert obs.volume == 12345 and obs.quote_currency == "USD"
    assert errors == []


def test_fmp_quote_sin_timestamp_no_fabrica_fecha():
    async def quote(ticker, max_retries=0):
        return [{"price": "273.5", "timestamp": 0}]

    observations, errors = _corre(_proveedor(fmp=_cliente(quote=quote)), [_empresa()])
    assert observations == {}
    assert errors[0]["reason"] == "FMP:quote_missing_timestamp"


def test_fmp_quote_en_futuro_rechazada():
    futuro = int(datetime(2026, 11, 8, 21, 0, tzinfo=UTC).timestamp())

    async def quote(ticker, max_retries=0):
        return [{"price": "273.5", "timestamp": futuro}]

    observations, errors = _corre(_proveedor(fmp=_cliente(quote=quote)), [_empresa()])
    assert observations == {}
    assert errors[0]["reason"] == "FMP:quote_date_in_future"


def test_fmp_429_marca_caido_y_el_resto_no_llama():
    llamadas = {"n": 0}

    async def quote(ticker, max_retries=0):
        llamadas["n"] += 1
        raise UpstreamRateLimited("429")

    breaker = _BreakerDict()
    provider = _proveedor(fmp=_cliente(quote=quote), breaker=breaker)
    observations, errors = _corre(provider, [_empresa("AAPL"), _empresa("MSFT")])
    assert llamadas["n"] == 1  # el segundo ticker no gasta cuota
    assert {e["ticker"] for e in errors} == {"AAPL", "MSFT"}
    assert all("FMP:provider_unavailable" in e["reason"] for e in errors)
    assert breaker.data["marketdata_breaker:fmp:429_streak"] == 1  # una por corrida


def test_fmp_error_generico_cae_a_finnhub():
    async def quote_fmp(ticker, max_retries=0):
        raise ValueError("payload raro")

    async def quote_finnhub(ticker, max_retries=0):
        return {"c": 273.5, "t": TS_QUOTE}

    provider = _proveedor(
        fmp=_cliente(quote=quote_fmp), finnhub=_cliente(quote=quote_finnhub)
    )
    observations, errors = _corre(provider, [_empresa()])
    obs = observations["AAPL"]
    assert (obs.price, obs.source, obs.quote_currency) == (
        Decimal("273.5"),
        "Finnhub",
        "USD",
    )
    assert errors == []


def test_finnhub_sin_timestamp_ni_proveedores_configurados():
    async def quote(ticker, max_retries=0):
        return {"c": 273.5, "t": 0}

    observations, errors = _corre(
        _proveedor(finnhub=_cliente(quote=quote)), [_empresa()]
    )
    assert observations == {}
    assert errors[0]["reason"] == "Finnhub:quote_missing_timestamp"

    observations, errors = _corre(_proveedor(), [_empresa()])
    assert errors[0]["reason"] == "no_price_provider_configured"


def test_breaker_abierto_salta_los_dos_proveedores():
    breaker = _BreakerDict()
    breaker.data["marketdata_breaker:fmp:open"] = "1"
    breaker.data["marketdata_breaker:finnhub:open"] = "1"
    llamadas = {"n": 0}

    async def quote(ticker, max_retries=0):
        llamadas["n"] += 1
        return []

    provider = _proveedor(
        fmp=_cliente(quote=quote), finnhub=_cliente(quote=quote), breaker=breaker
    )
    observations, errors = _corre(provider, [_empresa()])
    assert llamadas["n"] == 0
    assert "FMP:provider_unavailable" in errors[0]["reason"]
    assert "Finnhub:provider_unavailable" in errors[0]["reason"]


def test_timeout_por_ticker(monkeypatch):
    monkeypatch.setattr(
        mrs.PublicPriceProvider, "PER_TICKER_TIMEOUT_SECONDS", 0.01
    )
    provider = _proveedor()

    async def lentisimo(company, as_of):
        await asyncio.sleep(5)
        return company, None, None

    provider._one = lentisimo
    observations, errors = _corre(provider, [_empresa()])
    assert observations == {}
    assert errors == [{"ticker": "AAPL", "reason": "per_ticker_timeout"}]
