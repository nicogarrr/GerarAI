"""Cableado al registry de salud de SEC (sec.py + sec_edgar.py), ESEF y OpenFIGI.

Fulfills: VAL-DATA-004 (extensión a wrappers SEC, ESEF y OpenFIGI)
Expected Behavior:
- SEC (clave compartida "sec_edgar"): 5xx/red/no-JSON/429 agotado degradan;
  400/404 (documento/CIK inexistente) NO degradan; éxito (directo o vía
  mirror HF, fallback declarado) cierra
- ESEF (filings.xbrl.org): 5xx/red degradan; 400/404 por filing neutral
- OpenFIGI: 429/5xx agotados y payload inválido degradan; 400 neutral; un
  "error" por identificador en el payload es respuesta válida (éxito)
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.connectors import esef, openfigi, sec, sec_edgar
from app.services.data_source_health import DataSourceHealthRegistry, get_data_source_registry


@pytest.fixture(autouse=True)
def fresh_registry():
    DataSourceHealthRegistry._instance = None
    yield
    DataSourceHealthRegistry._instance = None


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _json_response(status: int, body: str = "{}") -> httpx.Response:
    return httpx.Response(status, text=body, headers={"content-type": "application/json"})


# ---------- SEC (sec.py) ----------


def test_registry_incluye_esef_y_openfigi():
    registry = get_data_source_registry()
    assert "esef" in registry.sources
    assert "openfigi" in registry.sources
    assert "sec_edgar" in registry.sources


def test_sec_client_500_degrada():
    def handler(request):
        return _json_response(500)

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    client = sec.SECClient(client=_mock_client(handler), max_retries=0)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.ticker_map())
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_sec_client_404_dato_no_degrada():
    def handler(request):
        return _json_response(404)

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    client = sec.SECClient(client=_mock_client(handler), max_retries=0)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.ticker_map())
    assert registry.get_status("sec_edgar").consecutive_failures == before


def test_sec_client_exito_cierra():
    def handler(request):
        return _json_response(200, '{"0":{"cik_str":320193,"ticker":"AAPL","title":"Apple"}}')

    registry = get_data_source_registry()
    registry.record_failure("sec_edgar", "fallo previo")
    client = sec.SECClient(client=_mock_client(handler), max_retries=0)
    payload = asyncio.run(client.ticker_map())
    assert payload["0"]["ticker"] == "AAPL"
    assert registry.get_status("sec_edgar").consecutive_failures == 0


# ---------- SEC EDGAR (sec_edgar.py, _get_json) ----------


def test_sec_edgar_429_agotado_degrada():
    def handler(request):
        return _json_response(429)

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(RuntimeError, match="request failed"):
        asyncio.run(
            sec_edgar._get_json(
                "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000000.json",
                client=_mock_client(handler),
                max_retries=0,
            )
        )
    assert registry.get_status("sec_edgar").consecutive_failures == before + 1


def test_sec_edgar_404_documento_no_degrada():
    def handler(request):
        return _json_response(404)

    registry = get_data_source_registry()
    before = registry.get_status("sec_edgar").consecutive_failures
    with pytest.raises(RuntimeError, match="404"):
        asyncio.run(
            sec_edgar._get_json(
                "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000000.json",
                client=_mock_client(handler),
                max_retries=0,
            )
        )
    assert registry.get_status("sec_edgar").consecutive_failures == before


def test_sec_edgar_exito_cierra():
    def handler(request):
        return _json_response(200, '{"cik": 320193}')

    registry = get_data_source_registry()
    registry.record_failure("sec_edgar", "fallo previo")
    data = asyncio.run(
        sec_edgar._get_json(
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
            client=_mock_client(handler),
            max_retries=0,
        )
    )
    assert data["cik"] == 320193
    assert registry.get_status("sec_edgar").consecutive_failures == 0


# ---------- ESEF ----------


def test_esef_500_degrada():
    def handler(request):
        return _json_response(500)

    registry = get_data_source_registry()
    before = registry.get_status("esef").consecutive_failures
    client = esef.EsefClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=esef.ESEF_BASE_URL)
    )
    with pytest.raises(esef.EsefError):
        asyncio.run(client.list_filings_page(country="ES"))
    assert registry.get_status("esef").consecutive_failures == before + 1


def test_esef_404_filing_no_degrada():
    def handler(request):
        return _json_response(404)

    registry = get_data_source_registry()
    before = registry.get_status("esef").consecutive_failures
    client = esef.EsefClient(client=_mock_client(handler))
    filing = esef.EsefFiling(
        fxo_id="x",
        lei="959800",
        country="ES",
        period_end="2025-12-31",
        json_url="https://filings.xbrl.org/x.json",
        package_url=None,
        sha256=None,
        error_count=None,
        warning_count=None,
    )
    with pytest.raises(esef.EsefError):
        asyncio.run(client.fetch_filing_json(filing))
    assert registry.get_status("esef").consecutive_failures == before


def test_esef_exito_cierra():
    def handler(request):
        return _json_response(200, '{"data":[],"meta":{"count":0}}')

    registry = get_data_source_registry()
    registry.record_failure("esef", "fallo previo")
    client = esef.EsefClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=esef.ESEF_BASE_URL)
    )
    filings, _total = asyncio.run(client.list_filings_page(country="ES"))
    assert filings == []
    assert registry.get_status("esef").consecutive_failures == 0


# ---------- OpenFIGI ----------


def test_openfigi_500_degrada():
    def handler(request):
        return _json_response(500)

    registry = get_data_source_registry()
    before = registry.get_status("openfigi").consecutive_failures
    client = openfigi.OpenFIGIClient(client=_mock_client(handler))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.map_identifier("US0378331005"))
    assert registry.get_status("openfigi").consecutive_failures == before + 1


def test_openfigi_400_job_no_degrada():
    def handler(request):
        return _json_response(400)

    registry = get_data_source_registry()
    before = registry.get_status("openfigi").consecutive_failures
    client = openfigi.OpenFIGIClient(client=_mock_client(handler))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.map_identifier("US0378331005"))
    assert registry.get_status("openfigi").consecutive_failures == before


def test_openfigi_error_por_identificador_es_exito():
    def handler(request):
        return _json_response(200, '[{"error":"No identifier found"}]')

    registry = get_data_source_registry()
    registry.record_failure("openfigi", "fallo previo")
    client = openfigi.OpenFIGIClient(client=_mock_client(handler))
    result = asyncio.run(client.map_identifier("US0378331005"))
    assert result["status"] == "error"
    assert registry.get_status("openfigi").consecutive_failures == 0


def test_openfigi_sync_429_agotado_degrada():
    class _FakeSyncClient:
        def post(self, url, json=None, headers=None):
            return httpx.Response(429, request=httpx.Request("POST", url))

    registry = get_data_source_registry()
    before = registry.get_status("openfigi").consecutive_failures
    connector = openfigi.OpenFIGIConnector(client=_FakeSyncClient(), max_retries=0)
    result = connector.map_identifier("US0378331005")
    assert result["status"] == "error"
    assert registry.get_status("openfigi").consecutive_failures == before + 1
