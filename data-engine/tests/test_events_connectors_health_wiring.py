"""Cableado al registry de salud de Nasdaq calendario, FINRA y CNMV cortos.

Fulfills: VAL-DATA-004 (extensión a conectores de eventos)
Expected Behavior:
- Nasdaq (earnings/dividends/IPO comparten _get_json): fallo de red, HTTP o
  no-JSON degradan; éxito cierra. El conector sigue devolviendo None al flujo
- FINRA diario: 404 "fichero aún no publicado" es exploración normal y NO
  degrada; red/401/403/429/5xx sí. FINRA quincenal: no-JSON/no-lista degradan
- CNMV cortos (clave "cnmv" compartida): HTTP/red/deriva de parseo degradan
"""

from __future__ import annotations

import asyncio
from datetime import date

import httpx
import pytest

from app.services.connectors import cnmv_shorts, earnings_calendar, ipo_calendar, short_interest
from app.services.data_source_health import DataSourceHealthRegistry, get_data_source_registry


@pytest.fixture(autouse=True)
def fresh_registry():
    DataSourceHealthRegistry._instance = None
    yield
    DataSourceHealthRegistry._instance = None


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------- Nasdaq (earnings_calendar._get_json compartido con ipo_calendar) ----------


def test_registry_incluye_nasdaq_y_finra():
    registry = get_data_source_registry()
    assert "nasdaq" in registry.sources
    assert "finra" in registry.sources
    assert "cnmv" in registry.sources


def test_nasdaq_red_caida_degrada_y_devuelve_none():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    registry = get_data_source_registry()
    before = registry.get_status("nasdaq").consecutive_failures
    result = asyncio.run(earnings_calendar.fetch_earnings_day(date(2026, 1, 5), client=_mock_client(handler)))
    assert result is None  # el flujo nunca se rompe
    assert registry.get_status("nasdaq").consecutive_failures == before + 1


def test_nasdaq_exito_cierra():
    def handler(request):
        return httpx.Response(200, json={"data": {"rows": []}})

    registry = get_data_source_registry()
    registry.record_failure("nasdaq", "fallo previo")
    result = asyncio.run(earnings_calendar.fetch_earnings_day(date(2026, 1, 5), client=_mock_client(handler)))
    assert result == []
    assert registry.get_status("nasdaq").consecutive_failures == 0


def test_nasdaq_ipo_comparte_circuito():
    def handler(request):
        return httpx.Response(500, text="")

    registry = get_data_source_registry()
    before = registry.get_status("nasdaq").consecutive_failures
    result = asyncio.run(ipo_calendar.fetch_ipo_month(date(2026, 1, 1), client=_mock_client(handler)))
    assert result is None or result == {} or isinstance(result, dict)
    assert registry.get_status("nasdaq").consecutive_failures == before + 1


# ---------- FINRA ----------


def test_finra_404_fichero_no_publicado_no_degrada():
    def handler(request):
        return httpx.Response(404, text="")

    registry = get_data_source_registry()
    before = registry.get_status("finra").consecutive_failures
    result = asyncio.run(
        short_interest.fetch_short_volume(
            "AAPL", date(2026, 1, 5), client=_mock_client(handler), lookback_days=2
        )
    )
    assert result is None
    assert registry.get_status("finra").consecutive_failures == before


def test_finra_429_degrada():
    def handler(request):
        return httpx.Response(429, text="")

    registry = get_data_source_registry()
    before = registry.get_status("finra").consecutive_failures
    result = asyncio.run(
        short_interest.fetch_short_volume(
            "AAPL", date(2026, 1, 5), client=_mock_client(handler), lookback_days=0
        )
    )
    assert result is None
    assert registry.get_status("finra").consecutive_failures == before + 1


def test_finra_quincenal_no_json_degrada():
    def handler(request):
        return httpx.Response(200, text="<html>no json</html>")

    registry = get_data_source_registry()
    before = registry.get_status("finra").consecutive_failures
    result = asyncio.run(short_interest._short_interest_page(0, 200, _mock_client(handler)))
    assert result is None
    assert registry.get_status("finra").consecutive_failures == before + 1


def test_finra_quincenal_exito_cierra():
    def handler(request):
        return httpx.Response(200, json=[])

    registry = get_data_source_registry()
    registry.record_failure("finra", "fallo previo")
    result = asyncio.run(short_interest._short_interest_page(0, 200, _mock_client(handler)))
    assert result == []
    assert registry.get_status("finra").consecutive_failures == 0


# ---------- CNMV cortos ----------


def _issuer():
    from app.services.cnmv_mapping import CNMVIssuer

    return CNMVIssuer(ticker="ENT", legal_name="ENTIDAD SA", nif="A-28000000", isin="ES0000000001")


def test_cnmv_shorts_deriva_parseo_degrada():
    def handler(request):
        return httpx.Response(200, text="<html><body>Sin la tabla esperada</body></html>")

    registry = get_data_source_registry()
    before = registry.get_status("cnmv").consecutive_failures
    with pytest.raises(ValueError):
        asyncio.run(cnmv_shorts.fetch_positions(_issuer(), client=_mock_client(handler)))
    assert registry.get_status("cnmv").consecutive_failures == before + 1


def test_cnmv_shorts_exito_cierra():
    page = (
        "<html><body>ES0000000001 ENTIDAD SA"
        "<table><caption>Notificaciones vivas iguales o superiores</caption>"
        "<tbody><tr><td>FONDO X</td><td>0,55</td><td>20/01/2026</td><td>obs</td></tr></tbody>"
        "</table></body></html>"
    )

    def handler(request):
        return httpx.Response(200, text=page)

    registry = get_data_source_registry()
    registry.record_failure("cnmv", "fallo previo")
    result = asyncio.run(cnmv_shorts.fetch_positions(_issuer(), client=_mock_client(handler)))
    assert result["positions"]
    assert registry.get_status("cnmv").consecutive_failures == 0
