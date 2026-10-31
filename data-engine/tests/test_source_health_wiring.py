"""Pruebas del cableado Yahoo/ECB al registry de salud de fuentes.

Fulfills: VAL-DATA-004
Expected Behavior:
- Yahoo y ECB registran sus outcomes en el DataSourceHealthRegistry: sin este
  cableado el circuit breaker nunca transitaba y un CAPTCHA, un cambio de
  formato o un bloqueo de IP dejaba la fuente caída con el panel en "healthy"
- Un 429/999 o un 200 con HTML (CAPTCHA / cambio de página) se registran como
  fallo con causa explícita; un ticker desconocido (chart vacío bien formado)
  NO degrada la fuente
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.connectors.ecb import ECBClient
from app.services.connectors.yahoo import YahooFinanceClient
from app.services.data_source_health import CircuitState, get_data_source_registry


@pytest.fixture(autouse=True)
def registry_limpio():
    """Deja el singleton como estaba: es global y otros tests lo leen."""
    registry = get_data_source_registry()
    snapshot = {key: (s.consecutive_failures, s.state) for key, s in registry.sources.items()}
    yield registry
    for key, (failures, state) in snapshot.items():
        source = registry.sources[key]
        source.consecutive_failures = failures
        source.state = state


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"{status}", request=request, response=response)


@pytest.mark.anyio
async def test_yahoo_429_registra_fallo_captcha(registry_limpio):
    registry = registry_limpio
    status = registry.get_status("yahoo_finance")
    before = status.consecutive_failures

    async def fake_get(self, url, params=None, headers=None):
        raise _http_error(429)

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(httpx.HTTPStatusError):
            await YahooFinanceClient().quote("AAPL")

    assert status.consecutive_failures == before + 1


@pytest.mark.anyio
async def test_yahoo_200_con_html_es_fallo_de_fuente(registry_limpio):
    """La señal de CAPTCHA / cambio de página: 200 con HTML en vez de JSON."""
    registry = registry_limpio
    status = registry.get_status("yahoo_finance")
    before = status.consecutive_failures

    async def fake_get(self, url, params=None, headers=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = lambda: None
        resp.json = MagicMock(side_effect=ValueError("Expecting value: line 1 column 1"))
        return resp

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(RuntimeError, match="CAPTCHA|cambio de HTML"):
            await YahooFinanceClient().quote("AAPL")

    assert status.consecutive_failures == before + 1


@pytest.mark.anyio
async def test_yahoo_ticker_desconocido_no_degrada_la_fuente(registry_limpio):
    """Chart vacío bien formado (ticker inexistente): la fuente respondió bien,
    no es un fallo del proveedor y el breaker no debe moverse."""
    registry = registry_limpio
    status = registry.get_status("yahoo_finance")
    before = status.consecutive_failures

    async def fake_get(self, url, params=None, headers=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"chart": {"result": None, "error": {"code": "Not Found"}}}
        return resp

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(RuntimeError, match="empty chart"):
            await YahooFinanceClient().quote("TICKERQUENOEXISTE")

    assert status.consecutive_failures == before


@pytest.mark.anyio
async def test_yahoo_exito_registra_acierto_y_recierra(registry_limpio):
    registry = registry_limpio
    status = registry.get_status("yahoo_finance")
    status.record_failure("fallo previo de prueba")

    async def fake_get(self, url, params=None, headers=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"chart": {"result": [{"meta": {"regularMarketPrice": 123.45}}]}}
        return resp

    with patch("httpx.AsyncClient.get", new=fake_get):
        meta = await YahooFinanceClient().quote("AAPL")

    assert meta["regularMarketPrice"] == 123.45
    assert status.consecutive_failures == 0
    assert status.state == CircuitState.CLOSED


@pytest.mark.anyio
async def test_ecb_xml_invalido_registra_fallo(registry_limpio):
    """El BCE devolviendo HTML de error o un XML distinto: fallo de fuente."""
    registry = registry_limpio
    status = registry.get_status("ecb")
    before = status.consecutive_failures

    async def fake_get(self, url, params=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = lambda: None
        resp.content = b"<html><body>Access Denied"
        return resp

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(RuntimeError, match="cambio de formato"):
            await ECBClient().conversion_rates(base_currency="EUR", quote_currencies={"USD"})

    assert status.consecutive_failures == before + 1


@pytest.mark.anyio
async def test_ecb_error_http_registra_fallo(registry_limpio):
    registry = registry_limpio
    status = registry.get_status("ecb")
    before = status.consecutive_failures

    async def fake_get(self, url, params=None):
        raise _http_error(503)

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(httpx.HTTPStatusError):
            await ECBClient().conversion_rates(base_currency="EUR", quote_currencies={"USD"})

    assert status.consecutive_failures == before + 1


@pytest.mark.anyio
async def test_yahoo_404_ticker_inexistente_no_degrada(registry_limpio):
    """404 de la chart API = símbolo inexistente o delistado: la fuente
    respondió; el circuito no debe moverse por un ticker."""
    registry = registry_limpio
    status = registry.get_status("yahoo_finance")
    before = status.consecutive_failures

    async def fake_get(self, url, params=None, headers=None):
        raise _http_error(404)

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(httpx.HTTPStatusError):
            await YahooFinanceClient().quote("TICKERQUENOEXISTE")

    assert status.consecutive_failures == before


@pytest.mark.anyio
async def test_historical_stress_registra_captcha_como_fallo(registry_limpio):
    """historical_stress_service llama a Yahoo por HTTP propio: sin este
    cableado su CAPTCHA/bloqueo era invisible en el registry."""
    from app.services.historical_stress_service import _CACHE, load_history

    _CACHE.clear()
    registry = registry_limpio
    status = registry.get_status("yahoo_finance")
    before = status.consecutive_failures

    async def fake_get(self, url, params=None, headers=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = lambda: None
        resp.json = MagicMock(side_effect=ValueError("Expecting value"))
        return resp

    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(ValueError):
            await load_history("AAPL")

    assert status.consecutive_failures == before + 1
