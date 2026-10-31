"""Cableado al registry de Yahoo quoteSummary (CA insiders) y tracefour (PDMR UK).

Expected Behavior:
- Yahoo: 429/5xx/red degradan "yahoo_finance"; 400/404 (símbolo) neutros; un
  200 sin la envoltura quoteSummary (challenge, cambio de API) NO es éxito
- Tracefour: red/4xx/5xx degradan "tracefour" (endpoint fijo: 404 = endpoint
  movido, no consulta); éxito solo tras validar {"data": [...]}
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.connectors import ca_insider_yahoo, uk_pdmr_tracefour
from app.services.data_source_health import DataSourceHealthRegistry, get_data_source_registry


@pytest.fixture(autouse=True)
def fresh_registry():
    DataSourceHealthRegistry._instance = None
    yield
    DataSourceHealthRegistry._instance = None


def _sync(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _async(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------- Yahoo (CA insiders) ----------


def test_ca_yahoo_429_degrada():
    def handler(request):
        return httpx.Response(429, text="")

    before = get_data_source_registry().get_status("yahoo_finance").consecutive_failures
    with pytest.raises(httpx.HTTPStatusError):
        ca_insider_yahoo.fetch_insider_transactions("BN", _sync(handler), "crumb123")
    assert get_data_source_registry().get_status("yahoo_finance").consecutive_failures == before + 1


def test_ca_yahoo_404_simbolo_no_degrada():
    def handler(request):
        return httpx.Response(404, text="")

    before = get_data_source_registry().get_status("yahoo_finance").consecutive_failures
    with pytest.raises(httpx.HTTPStatusError):
        ca_insider_yahoo.fetch_insider_transactions("NOEXISTE", _sync(handler), "crumb123")
    assert get_data_source_registry().get_status("yahoo_finance").consecutive_failures == before


def test_ca_yahoo_200_sin_quotesummary_no_es_exito():
    def handler(request):
        return httpx.Response(200, text="<html><body>challenge</body></html>")

    before = get_data_source_registry().get_status("yahoo_finance").consecutive_failures
    with pytest.raises(ValueError):
        ca_insider_yahoo.fetch_insider_transactions("BN", _sync(handler), "crumb123")
    assert get_data_source_registry().get_status("yahoo_finance").consecutive_failures == before + 1


def test_ca_yahoo_200_json_sin_envoltura_no_es_exito():
    def handler(request):
        return httpx.Response(200, json={"finance": {"error": "bad crumb"}})

    before = get_data_source_registry().get_status("yahoo_finance").consecutive_failures
    with pytest.raises(ValueError):
        ca_insider_yahoo.fetch_insider_transactions("BN", _sync(handler), "crumb123")
    assert get_data_source_registry().get_status("yahoo_finance").consecutive_failures == before + 1


def test_ca_yahoo_simbolo_sin_modulo_es_exito_vacio():
    def handler(request):
        return httpx.Response(200, json={"quoteSummary": {"result": [], "error": None}})

    registry = get_data_source_registry()
    registry.record_failure("yahoo_finance", "fallo previo")
    out = ca_insider_yahoo.fetch_insider_transactions("BN", _sync(handler), "crumb123")
    assert out == []
    assert get_data_source_registry().get_status("yahoo_finance").consecutive_failures == 0


def test_ca_yahoo_crumb_invalido_degrada():
    def handler(request):
        return httpx.Response(
            200, text="<html>blocked page muy larga para ser un crumb valido de yahoo finance</html>"
        )

    before = get_data_source_registry().get_status("yahoo_finance").consecutive_failures
    with pytest.raises(RuntimeError, match="yahoo_crumb_unavailable"):
        ca_insider_yahoo.yahoo_session(_sync(handler))
    assert get_data_source_registry().get_status("yahoo_finance").consecutive_failures == before + 1


# ---------- Tracefour (PDMR UK) ----------


def test_tracefour_429_degrada():
    def handler(request):
        return httpx.Response(429, text="")

    before = get_data_source_registry().get_status("tracefour").consecutive_failures
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(uk_pdmr_tracefour.fetch_pdmr_feed(_async(handler)))
    assert get_data_source_registry().get_status("tracefour").consecutive_failures == before + 1


def test_tracefour_404_endpoint_movido_degrada():
    def handler(request):
        return httpx.Response(404, text="")

    before = get_data_source_registry().get_status("tracefour").consecutive_failures
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(uk_pdmr_tracefour.fetch_pdmr_feed(_async(handler)))
    assert get_data_source_registry().get_status("tracefour").consecutive_failures == before + 1


def test_tracefour_200_no_json_no_es_exito():
    def handler(request):
        return httpx.Response(200, text="<html><body>challenge</body></html>")

    before = get_data_source_registry().get_status("tracefour").consecutive_failures
    with pytest.raises(ValueError):
        asyncio.run(uk_pdmr_tracefour.fetch_pdmr_feed(_async(handler)))
    assert get_data_source_registry().get_status("tracefour").consecutive_failures == before + 1


def test_tracefour_200_sin_data_no_es_exito():
    def handler(request):
        return httpx.Response(200, json={"error": "maintenance"})

    before = get_data_source_registry().get_status("tracefour").consecutive_failures
    with pytest.raises(RuntimeError):
        asyncio.run(uk_pdmr_tracefour.fetch_pdmr_feed(_async(handler)))
    assert get_data_source_registry().get_status("tracefour").consecutive_failures == before + 1


def test_tracefour_feed_valido_cierra():
    def handler(request):
        return httpx.Response(200, json={"data": []})

    registry = get_data_source_registry()
    registry.record_failure("tracefour", "fallo previo")
    out = asyncio.run(uk_pdmr_tracefour.fetch_pdmr_feed(_async(handler)))
    assert out == []
    assert get_data_source_registry().get_status("tracefour").consecutive_failures == 0


def test_ca_yahoo_200_error_interno_unauthorized_degrada():
    """{quoteSummary:{result:null,error:{code:'Unauthorized'}}} NO es healthy."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "quoteSummary": {
                    "result": None,
                    "error": {"code": "Unauthorized", "description": "Invalid crumb"},
                }
            },
        )

    before = get_data_source_registry().get_status("yahoo_finance").consecutive_failures
    with pytest.raises(ValueError):
        ca_insider_yahoo.fetch_insider_transactions("BN", _sync(handler), "crumb-caducado")
    assert get_data_source_registry().get_status("yahoo_finance").consecutive_failures == before + 1


def test_ca_yahoo_200_result_null_sin_error_no_es_exito():
    def handler(request):
        return httpx.Response(200, json={"quoteSummary": {"result": None, "error": None}})

    before = get_data_source_registry().get_status("yahoo_finance").consecutive_failures
    with pytest.raises(ValueError):
        ca_insider_yahoo.fetch_insider_transactions("BN", _sync(handler), "crumb123")
    assert get_data_source_registry().get_status("yahoo_finance").consecutive_failures == before + 1


def test_ca_yahoo_lista_interna_valida_cierra():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "quoteSummary": {
                    "result": [{"insiderTransactions": {"transactions": [{"filerName": "X"}]}}],
                    "error": None,
                }
            },
        )

    registry = get_data_source_registry()
    registry.record_failure("yahoo_finance", "fallo previo")
    out = ca_insider_yahoo.fetch_insider_transactions("BN", _sync(handler), "crumb123")
    assert out == [{"filerName": "X"}]
    assert get_data_source_registry().get_status("yahoo_finance").consecutive_failures == 0
