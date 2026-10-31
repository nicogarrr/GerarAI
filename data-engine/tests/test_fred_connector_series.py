"""Tests del conector FRED: series(), series_csv() y fetch_observations().

Complementa test_free_data_connectors.py (degradacion sin clave, alias):
aqui se cubren los caminos con respuesta HTTP — parametros de la peticion,
contrato del CSV de fredgraph, y registro de salud de la fuente. Los fallos
de fuente (429, 5xx, red) deben registrarse en el registry; un 400/404 de
serie inexistente NO es la fuente caida y no debe registrar fallo.
"""

import asyncio

import httpx
import pytest

from app.services.connectors import fred as fred_connector
from app.services.connectors.base import UpstreamRateLimited
from app.services.connectors.fred import FREDClient
from app.services.data_source_health import get_data_source_registry


def run_async(coroutine):
    return asyncio.run(coroutine)


def _client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


def _fred_key(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")


def _fred_failures() -> int:
    return get_data_source_registry().get_status("fred").consecutive_failures


def test_client_configured_refleja_la_clave(monkeypatch):
    _fred_key(monkeypatch)
    assert FREDClient().configured() is True
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(fred_connector.get_settings(), "fred_api_key", None)
    assert FREDClient().configured() is False


def test_series_happy_path_parametros_y_exito_registrado(monkeypatch):
    _fred_key(monkeypatch)
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"observations": [{"date": "2024-01-01", "value": "5.3"}]}, request=request)

    async def probe():
        async with _client(handler) as client:
            return await FREDClient(client=client).series("CPIAUCSL", limit=7)

    payload = run_async(probe())
    assert payload["observations"][0]["value"] == "5.3"
    assert seen["params"]["series_id"] == "CPIAUCSL"
    assert seen["params"]["api_key"] == "test-key"
    assert seen["params"]["file_type"] == "json"
    assert seen["params"]["limit"] == "7"
    assert seen["params"]["sort_order"] == "desc"
    assert _fred_failures() == 0  # exito registrado: contador de fallos a cero


def test_series_400_es_serie_inexistente_no_fuente_caida(monkeypatch):
    _fred_key(monkeypatch)
    before = _fred_failures()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error_message": "Bad series"}, request=request)

    async def probe():
        async with _client(handler) as client:
            await FREDClient(client=client).series("NOEXISTE")

    with pytest.raises(httpx.HTTPStatusError):
        run_async(probe())
    assert _fred_failures() == before  # no se marca la fuente caida


def test_series_429_agotado_registra_fallo_y_relancia(monkeypatch):
    _fred_key(monkeypatch)
    before = _fred_failures()

    async def handler(request: httpx.Request) -> httpx.Response:
        # Retry-After mayor que el cap: get_with_retry pospone sin reintentar
        return httpx.Response(429, headers={"Retry-After": "9999"}, request=request)

    async def probe():
        async with _client(handler) as client:
            await FREDClient(client=client).series("CPIAUCSL")

    with pytest.raises(UpstreamRateLimited):
        run_async(probe())
    assert _fred_failures() == before + 1


def test_series_5xx_registra_fallo(monkeypatch):
    _fred_key(monkeypatch)
    before = _fred_failures()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    async def probe():
        async with _client(handler) as client:
            await FREDClient(client=client).series("CPIAUCSL")

    with pytest.raises(httpx.HTTPStatusError):
        run_async(probe())
    assert _fred_failures() > before


def test_series_csv_parsea_invierte_y_limita(monkeypatch):
    csv = (
        "observation_date,CPIAUCSL\n"
        "2024-01-01,300.0\n"
        "2024-02-01,301.5\n"
        "\n"
        "2024-03-01,302.1\n"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert "fredgraph.csv?id=CPIAUCSL" in str(request.url)
        return httpx.Response(200, text=csv, request=request)

    async def probe():
        async with _client(handler) as client:
            return await FREDClient(client=client).series_csv("CPIAUCSL", limit=2)

    out = run_async(probe())
    assert out == {
        "observations": [
            {"date": "2024-03-01", "value": "302.1"},
            {"date": "2024-02-01", "value": "301.5"},
        ]
    }
    assert _fred_failures() == 0


def test_series_csv_html_challenge_no_es_salud(monkeypatch):
    before = _fred_failures()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>challenge</body></html>", request=request)

    async def probe():
        async with _client(handler) as client:
            await FREDClient(client=client).series_csv("CPIAUCSL")

    with pytest.raises(RuntimeError, match="cabecera esperada"):
        run_async(probe())
    assert _fred_failures() == before + 1  # un 200 con HTML no registra exito


def test_series_csv_cabecera_distinta_no_es_salud(monkeypatch):
    before = _fred_failures()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="foo,bar\n2024-01-01,1.0\n", request=request)

    async def probe():
        async with _client(handler) as client:
            await FREDClient(client=client).series_csv("CPIAUCSL")

    with pytest.raises(RuntimeError, match="cabecera esperada"):
        run_async(probe())
    assert _fred_failures() == before + 1


def test_fetch_observations_fija_series_id_y_parametros(monkeypatch):
    _fred_key(monkeypatch)
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"observations": []}, request=request)

    async def probe():
        async with _client(handler) as client:
            return await fred_connector.fetch_observations("unemployment", limit=3, client=client)

    data = run_async(probe())
    assert data["series_id"] == "UNRATE"  # inyectado aunque el payload no lo traiga
    assert seen["params"]["series_id"] == "UNRATE"
    assert seen["params"]["limit"] == "3"
    assert seen["params"]["sort_order"] == "desc"


def test_latest_observation_valor_no_numerico_se_conserva(monkeypatch):
    _fred_key(monkeypatch)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"observations": [{"date": "2024-01-01", "value": "N/A"}]}, request=request)

    async def probe():
        async with _client(handler) as client:
            return await fred_connector.latest_observation("cpi", client=client)

    out = run_async(probe())
    assert out == {"series_id": "CPIAUCSL", "date": "2024-01-01", "value": "N/A"}


def test_latest_observation_sin_puntos_validos_es_none(monkeypatch):
    _fred_key(monkeypatch)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"observations": [{"date": "2024-01-01", "value": "."}, {"date": "2024-02-01", "value": ""}]},
            request=request,
        )

    async def probe():
        async with _client(handler) as client:
            return await fred_connector.latest_observation("cpi", client=client)

    assert run_async(probe()) is None


def test_latest_observation_indicador_invalido_propaga_value_error(monkeypatch):
    _fred_key(monkeypatch)
    with pytest.raises(ValueError, match="no es un alias"):
        run_async(fred_connector.latest_observation("esto no es un indicador valido para fred"))
