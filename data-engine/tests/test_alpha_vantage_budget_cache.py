"""Pruebas del presupuesto diario, caché/dedup y health sin cuota de Alpha Vantage.

Fulfills: VAL-DATA-002
Expected Behavior:
- Caché de respuestas: una segunda llamada al mismo dato NO sale a la red y se
  devuelve etiquetada (from_cache=True, fetched_at del momento de captura)
- Dedup en vuelo: N peticiones concurrentes al mismo dato gastan 1 llamada
- Presupuesto diario (free tier 25 req/día) persistente: los rechazos no salen
  a la red; las llamadas fallidas también cuentan (el proveedor las cuenta)
- El aviso de cuota diaria del proveedor ("25 requests per day") marca el día
  agotado y corta llamadas posteriores sin salir a la red
- Health check de cuota (quota_status y /api/health/data-sources) con CERO
  llamadas HTTP al proveedor
"""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.services.connectors.alpha_vantage as av_mod
from app.api.routes.health import router as health_router
from app.services.connectors.alpha_vantage import (
    AV_DAILY_LIMIT,
    AlphaVantageClient,
    AlphaVantageDailyBudget,
    AlphaVantageQuotaExhausted,
    AlphaVantageRateLimiter,
    _is_daily_limit_message,
)


def _quote_payload(symbol: str = "AAPL") -> dict:
    return {
        "Global Quote": {
            "01. symbol": symbol,
            "05. price": "123.45",
            "06. volume": "1000",
            "07. latest trading day": "2026-10-30",
            "08. previous close": "120.00",
            "09. change": "3.45",
            "10. change percent": "2.87%",
        }
    }


def _response(payload: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json = lambda: payload
    resp.raise_for_status = lambda: None
    return resp


def _client(limit: int = 25, dates: list | None = None) -> AlphaVantageClient:
    """Cliente hermético: sin Redis, sin esperas de tasa, fecha controlable."""
    date_fn = (lambda: dates[0]) if dates is not None else None
    budget = AlphaVantageDailyBudget(limit=limit, date_fn=date_fn, redis_client_fn=lambda: None)
    return AlphaVantageClient(
        api_key="TEST_KEY",
        budget=budget,
        rate_limiter=AlphaVantageRateLimiter(min_interval=0),
    )


@pytest.mark.anyio
async def test_cache_hit_no_gasta_red():
    """La segunda llamada al mismo dato se sirve de caché sin salir a la red."""
    client = _client()
    calls = 0

    async def fake_get(self, url, params=None):
        nonlocal calls
        calls += 1
        return _response(_quote_payload())

    with patch("httpx.AsyncClient.get", new=fake_get):
        first = await client.quote("AAPL")
        second = await client.quote("AAPL")

    assert calls == 1
    assert first["from_cache"] is False
    assert second["from_cache"] is True
    # La caché conserva la fecha de captura real: nunca se disfraza de dato fresco
    assert second["fetched_at"] == first["fetched_at"]
    assert first["price"] == 123.45
    assert client.budget.status()["used"] == 1


@pytest.mark.anyio
async def test_dedup_peticiones_concurrentes():
    """Dos peticiones concurrentes idénticas gastan UNA llamada de red."""
    client = _client()
    calls = 0

    async def fake_get(self, url, params=None):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)  # solapa las dos peticiones en vuelo
        return _response(_quote_payload())

    with patch("httpx.AsyncClient.get", new=fake_get):
        a, b = await asyncio.gather(client.quote("AAPL"), client.quote("AAPL"))

    assert calls == 1
    assert a["price"] == b["price"] == 123.45
    assert client.budget.status()["used"] == 1


@pytest.mark.anyio
async def test_presupuesto_diario_rechaza_sin_red_y_sirve_cache():
    """Agotado el presupuesto: no sale a la red, lanza QuotaExhausted, y la
    caché de llamadas anteriores se sigue sirviendo."""
    client = _client(limit=2)
    calls = 0

    async def fake_get(self, url, params=None):
        nonlocal calls
        calls += 1
        symbol = params["symbol"]
        return _response(_quote_payload(symbol))

    with patch("httpx.AsyncClient.get", new=fake_get):
        await client.quote("AAPL")
        await client.quote("MSFT")
        assert calls == 2
        assert client.budget.status()["used"] == 2

        with pytest.raises(AlphaVantageQuotaExhausted) as exc_info:
            await client.quote("GOOG")
        assert calls == 2  # el rechazo NO salió a la red
        assert exc_info.value.limit == 2
        assert exc_info.value.used == 2

        # La caché sigue disponible con la cuota agotada (degradación elegante)
        cached = await client.quote("AAPL")
        assert cached["from_cache"] is True
        assert calls == 2


@pytest.mark.anyio
async def test_llamada_fallida_tambien_cuenta_en_el_presupuesto():
    """Una llamada que falla a nivel de red gasta presupuesto: el proveedor
    también la cuenta. Nunca se devuelve cuota "a mano"."""
    import httpx

    client = _client(limit=3)
    calls = 0

    async def fake_get(self, url, params=None):
        nonlocal calls
        calls += 1
        if params["symbol"] == "AAPL":
            raise httpx.ConnectError("connection refused")
        return _response(_quote_payload(params["symbol"]))

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(httpx.ConnectError):
            await client.quote("AAPL")
        # La reserva es por INTENTO real: el fallo con reintento gastó 2
        assert client.budget.status()["used"] == 2
        await client.quote("MSFT")
        assert client.budget.status()["used"] == 3
        with pytest.raises(AlphaVantageQuotaExhausted):
            await client.quote("GOOG")
    # 2 intentos del fallo (max_retries=1) + 1 del éxito; el rechazo no salió
    assert calls == 3


@pytest.mark.anyio
async def test_mensaje_cuota_diaria_del_proveedor_corta_el_dia():
    """El aviso '25 requests per day' en JSON 200 marca el día agotado y las
    llamadas siguientes se rechazan sin salir a la red."""
    client = _client()
    calls = 0
    daily_msg = "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."

    async def fake_get(self, url, params=None):
        nonlocal calls
        calls += 1
        return _response({"Information": daily_msg})

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(AlphaVantageQuotaExhausted):
            await client.quote("AAPL")
        with pytest.raises(AlphaVantageQuotaExhausted):
            await client.quote("MSFT")
    assert calls == 1  # la segunda ni salió a la red
    assert client.budget.status()["remaining"] == 0


def test_clasificacion_mensajes_limite():
    """La heurística distingue cuota diaria de frecuencia por minuto."""
    assert _is_daily_limit_message("Our standard API rate limit is 25 requests per day.") is True
    assert _is_daily_limit_message("call frequency is 5 calls per minute") is False
    assert _is_daily_limit_message("frequency is 5 calls per minute and 25 calls per day") is False


def test_presupuesto_reinicia_al_cambiar_de_dia():
    """El contador es por día UTC: al día siguiente vuelve a haber presupuesto."""
    dates = [date(2026, 10, 31)]
    budget = AlphaVantageDailyBudget(limit=1, date_fn=lambda: dates[0], redis_client_fn=lambda: None)
    assert budget.reserve() is True
    assert budget.reserve() is False
    assert budget.status()["remaining"] == 0

    dates[0] = date(2026, 11, 1)
    assert budget.reserve() is True
    assert budget.status()["used"] == 1


class _FakeRedis:
    """Redis mínimo en memoria para probar la persistencia del presupuesto."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def eval(self, script, numkeys, key, limit, ttl):
        used = int(self.store.get(key, 0))
        if used >= int(limit):
            return [0, used]
        used += 1
        self.store[key] = str(used)
        return [1, used]

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = str(value)


def test_presupuesto_persistente_compartido_entre_procesos():
    """Dos instancias (dos procesos) comparten el contador vía Redis: un deploy
    a media tarde no reinicia el presupuesto."""
    fake = _FakeRedis()
    b1 = AlphaVantageDailyBudget(limit=2, redis_client_fn=lambda: fake)
    b2 = AlphaVantageDailyBudget(limit=2, redis_client_fn=lambda: fake)

    assert b1.reserve() is True
    assert b2.reserve() is True
    assert b1.reserve() is False  # tercera: agotado para AMBOS procesos
    assert b2.status()["used"] == 2
    assert b2.status()["backend"] == "redis"

    # La marca de agotado del proveedor se propaga por Redis
    b1.mark_exhausted()
    b3 = AlphaVantageDailyBudget(limit=2, redis_client_fn=lambda: fake)
    assert b3.used_today() == 2


def test_quota_status_no_llama_a_la_red():
    """El health check de cuota es local: cero HTTP aunque se consulte en bucle."""
    client = _client()
    with patch("httpx.AsyncClient.get", new=AsyncMock()) as mock_get:
        status = client.quota_status()
        client.quota_status()
        client.quota_status()
        mock_get.assert_not_called()

    assert status["configured"] is True
    assert status["daily_limit"] == AV_DAILY_LIMIT == 25
    assert status["used_today"] == 0
    assert status["remaining_today"] == 25
    assert status["allowed"] is True


def test_quota_status_sin_clave_no_permite_llamadas():
    client = AlphaVantageClient(api_key="", budget=AlphaVantageDailyBudget(redis_client_fn=lambda: None))
    status = client.quota_status()
    assert status["configured"] is False
    assert status["allowed"] is False


def test_health_endpoint_expone_cuota_sin_gastarla(monkeypatch):
    """GET /api/health/data-sources incluye la cuota de Alpha Vantage leyendo
    solo el contador local: la sonda nunca gasta cuota del proveedor."""
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "TEST_KEY_HEALTH")
    monkeypatch.setattr(av_mod, "_default_client", None)

    app = FastAPI()
    app.include_router(health_router, prefix="/api")
    with patch("httpx.AsyncClient.get", new=AsyncMock()) as mock_get:
        resp = TestClient(app).get("/api/health/data-sources")
        assert resp.status_code == 200
        sources = resp.json()["sources"]
        av = next(s for s in sources if s["name"] == "Alpha Vantage")
        mock_get.assert_not_called()

    assert av["quota"]["daily_limit"] == 25
    assert av["quota"]["remaining_today"] == 25
    assert av["quota"]["configured"] is True


@pytest.mark.anyio
async def test_sin_clave_no_gasta_presupuesto_ni_red():
    """Sin API key la llamada falla antes de reservar presupuesto o salir a la red."""
    client = AlphaVantageClient(
        api_key="",
        budget=AlphaVantageDailyBudget(redis_client_fn=lambda: None),
        rate_limiter=AlphaVantageRateLimiter(min_interval=0),
    )
    with patch("httpx.AsyncClient.get", new=AsyncMock()) as mock_get:
        with pytest.raises(RuntimeError, match="no está configurado"):
            await client.quote("AAPL")
        mock_get.assert_not_called()
    assert client.budget.status()["used"] == 0


@pytest.mark.anyio
async def test_ticker_se_envia_completo_sin_truncar():
    """SAN.MC se pide como SAN.MC: truncarlo a SAN devolvía el ADR americano,
    otra empresa con otro precio (veracidad)."""
    client = _client()
    requested: list[str] = []

    async def fake_get(self, url, params=None):
        requested.append(params["symbol"])
        return _response(_quote_payload(params["symbol"]))

    with patch("httpx.AsyncClient.get", new=fake_get):
        quote = await client.quote("SAN.MC")
    assert requested == ["SAN.MC"]
    assert quote["symbol"] == "SAN.MC"


@pytest.mark.anyio
async def test_respuesta_de_otra_empresa_se_rechaza():
    """Si Alpha Vantage responde con otro símbolo, la respuesta se rechaza:
    nunca se sirve la empresa equivocada como si fuera la pedida."""
    client = _client()

    async def fake_get(self, url, params=None):
        # Pedimos SAN.MC y llega el ADR americano SAN
        return _response(_quote_payload("SAN"))

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(RuntimeError, match="otra empresa"):
            await client.quote("SAN.MC")


@pytest.mark.anyio
async def test_metricas_none_no_rompen_ni_se_inventan():
    """Alpha Vantage serializa huecos como la cadena "None": antes rompía el
    float() y el `or 0.0` inventaba ceros. Ahora: None = sin dato."""
    client = _client()
    payload = {
        "Symbol": "XYZ",
        "Name": "Empresa X",
        "Description": "",
        "Sector": "Technology",
        "Industry": "",
        "MarketCapitalization": "None",
        "PERatio": "None",
        "PriceToBookRatio": "None",
        "DividendYield": "None",
        "EPS": "None",
    }

    async def fake_get(self, url, params=None):
        return _response(payload)

    with patch("httpx.AsyncClient.get", new=fake_get):
        overview = await client.overview("XYZ")

    assert overview["symbol"] == "XYZ"
    assert overview["market_cap"] is None
    assert overview["pe_ratio"] is None
    assert overview["pb_ratio"] is None
    assert overview["dividend_yield"] is None
    assert overview["eps"] is None


@pytest.mark.anyio
async def test_quote_sin_precio_se_rechaza():
    """Una cotización sin precio no se sirve: price=None sería un dato roto."""
    client = _client()
    payload = _quote_payload()
    payload["Global Quote"]["05. price"] = "None"

    async def fake_get(self, url, params=None):
        return _response(payload)

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(RuntimeError, match="sin precio"):
            await client.quote("AAPL")


def _429_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {}
    resp.raise_for_status = lambda: None
    return resp


@pytest.mark.anyio
async def test_429_con_presupuesto_1_el_reintento_no_sale_a_la_red():
    """Con presupuesto restante 1 y un 429, el reintento de get_with_retry NO
    sale a la red: la reserva es por intento real y el tope de 25/día queda
    garantizado aunque haya reintentos."""
    client = _client(limit=1)
    calls = 0

    async def fake_get(self, url, params=None):
        nonlocal calls
        calls += 1
        return _429_response()

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(AlphaVantageQuotaExhausted):
            await client.quote("AAPL")
    assert calls == 1  # solo salió el primer intento
    assert client.budget.status()["used"] == 1


@pytest.mark.anyio
async def test_429_tras_reintento_con_presupuesto_exito():
    """Con presupuesto para los 2 intentos, un 429 seguido de éxito gasta 2
    unidades (el proveedor cuenta ambas) y devuelve el dato."""
    client = _client(limit=2)
    calls = 0

    async def fake_get(self, url, params=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _429_response()
        return _response(_quote_payload())

    with patch("httpx.AsyncClient.get", new=fake_get):
        quote = await client.quote("AAPL")
    assert quote["price"] == 123.45
    assert calls == 2
    assert client.budget.status()["used"] == 2


@pytest.mark.anyio
async def test_nan_e_infinito_no_son_dato():
    """float("NaN") y float("Infinity") parsean pero no son un dato: None."""
    client = _client()
    payload = {
        "Symbol": "XYZ",
        "Name": "Empresa X",
        "MarketCapitalization": "Infinity",
        "PERatio": "NaN",
        "PriceToBookRatio": "-Infinity",
        "DividendYield": "1.5",
        "EPS": "None",
    }

    async def fake_get(self, url, params=None):
        return _response(payload)

    with patch("httpx.AsyncClient.get", new=fake_get):
        overview = await client.overview("XYZ")

    assert overview["market_cap"] is None
    assert overview["pe_ratio"] is None
    assert overview["pb_ratio"] is None
    assert overview["dividend_yield"] == 1.5
    assert overview["eps"] is None


@pytest.mark.anyio
async def test_quote_precio_nan_se_rechaza():
    """Una cotización con precio NaN no se sirve: price=None sería dato roto."""
    client = _client()
    payload = _quote_payload()
    payload["Global Quote"]["05. price"] = "NaN"

    async def fake_get(self, url, params=None):
        return _response(payload)

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(RuntimeError, match="sin precio"):
            await client.quote("AAPL")
