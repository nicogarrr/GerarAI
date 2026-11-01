"""Cableado al registry de salud de Stooq, Finnhub, FMP y Damodaran.

Fulfills: VAL-DATA-004 (extensión a conectores de mercado extra)
Expected Behavior:
- Stooq: 5xx/red/HTML challenge/CSV roto degradan; "No data" y 400/404 no
- Finnhub/FMP: 429 (UpstreamRateLimited), 401/403 y 5xx degradan; 400/404
  (y 402 entitlement por endpoint en FMP) NO degradan
- Damodaran: descarga fallida o xlsx sin filas válidas degradan; éxito cierra
"""

from __future__ import annotations

import asyncio
import io
from datetime import date, datetime

import httpx
import openpyxl
import pytest

from app.services.connectors import damodaran, finnhub, fmp, stooq
from app.services.connectors.base import UpstreamRateLimited
from app.services.data_source_health import DataSourceHealthRegistry, get_data_source_registry


@pytest.fixture(autouse=True)
def fresh_registry():
    DataSourceHealthRegistry._instance = None
    yield
    DataSourceHealthRegistry._instance = None


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------- Stooq ----------


def test_registry_incluye_fuentes_mercado():
    registry = get_data_source_registry()
    for key in ("stooq", "finnhub", "fmp", "damodaran"):
        assert key in registry.sources, key


def test_stooq_challenge_html_degrada():
    def handler(request):
        return httpx.Response(200, text="<html><body>challenge</body></html>")

    registry = get_data_source_registry()
    before = registry.get_status("stooq").consecutive_failures
    client = stooq.StooqClient(client=_mock_client(handler))
    with pytest.raises(RuntimeError, match="HTML"):
        asyncio.run(client.daily_prices("aapl.us", start=date(2026, 1, 1), end=date(2026, 1, 31)))
    assert registry.get_status("stooq").consecutive_failures == before + 1


def test_stooq_no_data_es_exito_no_fallo():
    def handler(request):
        return httpx.Response(200, text="No data")

    registry = get_data_source_registry()
    registry.record_failure("stooq", "fallo previo")
    client = stooq.StooqClient(client=_mock_client(handler))
    result = asyncio.run(client.daily_prices("zzz.us", start=date(2026, 1, 1), end=date(2026, 1, 31)))
    assert result == []
    assert registry.get_status("stooq").consecutive_failures == 0


def test_stooq_500_degrada():
    def handler(request):
        return httpx.Response(500, text="")

    registry = get_data_source_registry()
    before = registry.get_status("stooq").consecutive_failures
    client = stooq.StooqClient(client=_mock_client(handler))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.daily_prices("aapl.us", start=date(2026, 1, 1), end=date(2026, 1, 31)))
    assert registry.get_status("stooq").consecutive_failures == before + 1


# ---------- Finnhub / FMP (falso AsyncClient a nivel de módulo) ----------


class _FakeResponse:
    def __init__(self, status: int, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.test")
            raise httpx.HTTPStatusError(
                "err", request=request, response=httpx.Response(self.status_code, request=request)
            )

    def json(self):
        return self._payload


def _patch_module_client(monkeypatch, module, response):
    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            return response

    monkeypatch.setattr(module.httpx, "AsyncClient", _FakeAsyncClient)


def test_finnhub_429_degrada(monkeypatch):
    _patch_module_client(monkeypatch, finnhub, _FakeResponse(429))
    client = finnhub.FinnhubClient()
    monkeypatch.setattr(client.settings, "finnhub_api_key", "test-key")
    registry = get_data_source_registry()
    before = registry.get_status("finnhub").consecutive_failures
    with pytest.raises(UpstreamRateLimited):
        asyncio.run(client.quote("AAPL", max_retries=0))
    assert registry.get_status("finnhub").consecutive_failures == before + 1


def test_finnhub_404_ticker_no_degrada(monkeypatch):
    _patch_module_client(monkeypatch, finnhub, _FakeResponse(404))
    client = finnhub.FinnhubClient()
    monkeypatch.setattr(client.settings, "finnhub_api_key", "test-key")
    registry = get_data_source_registry()
    before = registry.get_status("finnhub").consecutive_failures
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.quote("NOEXISTE", max_retries=0))
    assert registry.get_status("finnhub").consecutive_failures == before


def test_finnhub_exito_cierra(monkeypatch):
    _patch_module_client(monkeypatch, finnhub, _FakeResponse(200, {"c": 123.4}))
    client = finnhub.FinnhubClient()
    monkeypatch.setattr(client.settings, "finnhub_api_key", "test-key")
    registry = get_data_source_registry()
    registry.record_failure("finnhub", "fallo previo")
    payload = asyncio.run(client.quote("AAPL", max_retries=0))
    assert payload["c"] == 123.4
    assert registry.get_status("finnhub").consecutive_failures == 0


def test_fmp_402_entitlement_no_degrada(monkeypatch):
    _patch_module_client(monkeypatch, fmp, _FakeResponse(402))
    client = fmp.FMPClient()
    monkeypatch.setattr(client.settings, "fmp_api_key", "test-key")
    registry = get_data_source_registry()
    before = registry.get_status("fmp").consecutive_failures
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.quote("AAPL", max_retries=0))
    assert registry.get_status("fmp").consecutive_failures == before


def test_fmp_429_degrada(monkeypatch):
    _patch_module_client(monkeypatch, fmp, _FakeResponse(429))
    client = fmp.FMPClient()
    monkeypatch.setattr(client.settings, "fmp_api_key", "test-key")
    registry = get_data_source_registry()
    before = registry.get_status("fmp").consecutive_failures
    with pytest.raises(UpstreamRateLimited):
        asyncio.run(client.quote("AAPL", max_retries=0))
    assert registry.get_status("fmp").consecutive_failures == before + 1


# ---------- Damodaran ----------


def _workbook_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Historical ERP"
    ws.append(
        (
            "Start of month",
            "S&P 500",
            "T.Bond Rate",
            "$ Riskfree Rate",
            "Ten-year average CF",
            "CF (Trailing 12 month)",
            "Normalized CF",
            "Expected growth rate",
            "ERP (T12 m with sustainable payout)",
            "ERP (T12m)",
        )
    )
    ws.append((datetime(2026, 9, 1), 7686.14, 0.0475, None, None, None, None, None, 0.0414, 0.0409))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_damodaran_descarga_fallida_degrada(monkeypatch):
    async def boom(url):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(damodaran, "_download", boom)
    damodaran.reset_cache()
    registry = get_data_source_registry()
    before = registry.get_status("damodaran").consecutive_failures
    assert asyncio.run(damodaran.implied_erp_series()) == []
    assert registry.get_status("damodaran").consecutive_failures == before + 1


def test_damodaran_xlsx_sin_filas_degrada(monkeypatch):
    async def fake_download(url):
        return b"contenido que no es un xlsx"

    monkeypatch.setattr(damodaran, "_download", fake_download)
    damodaran.reset_cache()
    registry = get_data_source_registry()
    before = registry.get_status("damodaran").consecutive_failures
    assert asyncio.run(damodaran.implied_erp_series()) == []
    assert registry.get_status("damodaran").consecutive_failures == before + 1


def test_damodaran_exito_cierra(monkeypatch):
    async def fake_download(url):
        return _workbook_bytes()

    monkeypatch.setattr(damodaran, "_download", fake_download)
    damodaran.reset_cache()
    registry = get_data_source_registry()
    registry.record_failure("damodaran", "fallo previo")
    rows = asyncio.run(damodaran.implied_erp_series())
    assert rows
    assert registry.get_status("damodaran").consecutive_failures == 0
