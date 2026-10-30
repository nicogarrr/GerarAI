"""Pruebas exhaustivas para la integración de fuentes de datos externas y circuit breakers.

Fulfills: VAL-DATA-001, VAL-DATA-002, VAL-DATA-003, VAL-DATA-004
Expected Behavior:
- Yahoo Finance integrado como fuente primaria (sin clave requerida)
- Alpha Vantage integrado como fuente secundaria con control de cuota (5 req/min)
- ECB integrado para tipos oficiales diarios y conversiones EUR
- Registro de salud y Circuit Breaker con failover automático a fuentes secundarias
- Endpoint HTTP GET /api/health/data-sources
"""

from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.health import router as health_router
from app.services.connectors.alpha_vantage import (
    AlphaVantageClient,
    AlphaVantageRateLimiter,
)
from app.services.connectors.ecb import ECBClient
from app.services.connectors.yahoo import YahooFinanceClient, yahoo_chart_symbol
from app.services.data_source_health import (
    CircuitState,
    get_data_source_registry,
)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(health_router, prefix="/api")
    return TestClient(app)


def test_yahoo_finance_connector():
    """Verifica el cliente de Yahoo Finance (VAL-DATA-001)."""
    client_yf = YahooFinanceClient()
    # No requiere clave: EUR0 compliant
    assert client_yf.configured() is True
    assert client_yf.name == "yahoo"

    # Conversión de símbolo para clases de acciones
    assert yahoo_chart_symbol("SAN.MC") == "SAN.MC"
    assert yahoo_chart_symbol("BRK.B") == "BRK-B"
    assert yahoo_chart_symbol("BF.A") == "BF-A"
    assert yahoo_chart_symbol("AAPL") == "AAPL"


def test_alpha_vantage_connector_and_rate_limiting():
    """Verifica el cliente de Alpha Vantage y su limitador de tasa (VAL-DATA-002)."""
    # Sin clave
    av_no_key = AlphaVantageClient(api_key="")
    assert av_no_key.configured() is False

    # Con clave
    av_with_key = AlphaVantageClient(api_key="TEST_KEY_123")
    assert av_with_key.configured() is True
    assert av_with_key.name == "alpha_vantage"

    # Comprobación de Rate Limiter
    limiter = AlphaVantageRateLimiter(min_interval=0.05)
    limiter.reset()

    t0 = time.perf_counter()
    limiter.wait()
    limiter.wait()
    elapsed = time.perf_counter() - t0
    assert elapsed >= 0.04


@pytest.mark.anyio
async def test_ecb_rates_parsing():
    """Verifica el cliente de tipos de cambio del BCE (VAL-DATA-003)."""
    sample_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-05-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
        <Cube>
            <Cube time="2026-10-30">
                <Cube currency="USD" rate="1.0850"/>
                <Cube currency="GBP" rate="0.8550"/>
                <Cube currency="CHF" rate="0.9420"/>
            </Cube>
        </Cube>
    </gesmes:Envelope>
    """

    ecb = ECBClient()
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.content = sample_xml
        mock_resp.raise_for_status = lambda: None
        mock_get.return_value = mock_resp

        rates = await ecb.conversion_rates(base_currency="EUR", quote_currencies={"USD", "GBP", "CHF"})
        assert rates.rate_date.isoformat() == "2026-10-30"
        # EUR base -> tasa para convertir de quote a EUR es 1 / rate
        assert rates.rates["USD"] == Decimal("1") / Decimal("1.0850")
        assert rates.rates["GBP"] == Decimal("1") / Decimal("0.8550")


def test_circuit_breaker_and_failover_logic():
    """Verifica el circuit breaker y la conmutación a fuentes secundarias (VAL-DATA-004)."""
    registry = get_data_source_registry()
    status = registry.get_status("yahoo_finance")
    status.record_success(15.2)
    assert status.state == CircuitState.CLOSED

    # Fallo 1 y 2 -> sigue CLOSED
    status.record_failure("HTTP 500 error")
    assert status.state == CircuitState.CLOSED
    status.record_failure("Timeout")
    assert status.state == CircuitState.CLOSED

    # Fallo 3 -> Abre el circuito (OPEN)
    status.record_failure("Connection refused")
    assert status.state == CircuitState.OPEN

    # Con circuito abierto, se activa el failover
    should_fallback, fallback_name = registry.should_use_fallback("yahoo_finance")
    assert should_fallback is True
    assert fallback_name == "alpha_vantage"

    # Éxito restablece el circuito a CLOSED
    status.record_success(12.0)
    assert status.state == CircuitState.CLOSED
    should_fallback_after, _ = registry.should_use_fallback("yahoo_finance")
    assert should_fallback_after is False


def test_data_sources_health_endpoint(client):
    """Verifica el endpoint HTTP GET /api/health/data-sources."""
    res = client.get("/api/health/data-sources")
    assert res.status_code == 200
    data = res.json()
    assert "overall_status" in data
    assert "sources" in data
    assert len(data["sources"]) >= 4

    source_names = [s["name"] for s in data["sources"]]
    assert "Yahoo Finance" in source_names
    assert "Alpha Vantage" in source_names
    assert "European Central Bank (ECB)" in source_names
