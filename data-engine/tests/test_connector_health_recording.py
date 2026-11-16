"""Los conectores de sondeo registran exito y fallo en el registro de salud.

Antes (Lote 1, hallazgo 3) subtel, fca_nsm, house_ptr y official_fx no
registraban nada: un fallo sostenido de la fuente era invisible para el
panel y el watchdog. Estos tests fijan ambos caminos por conector.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services.connectors import fca_nsm, house_ptr, official_fx, subtel

FIXTURE = Path(__file__).parent / "fixtures/subtel"


class _Registry:
    def __init__(self):
        self.successes: list[tuple[str, float]] = []
        self.failures: list[tuple[str, str]] = []

    def record_success(self, key: str, elapsed_ms: float = 0.0):
        self.successes.append((key, elapsed_ms))

    def record_failure(self, key: str, error: str):
        self.failures.append((key, error))


@pytest.fixture
def registry(monkeypatch):
    reg = _Registry()
    for module in (subtel, fca_nsm, house_ptr, official_fx):
        monkeypatch.setattr(module, "get_data_source_registry", lambda: reg)
    return reg


# -- subtel -------------------------------------------------------------------


def _subtel_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_subtel_exito_registra_success(registry):
    def handler(request):
        body = ((FIXTURE / "request-10872.html").read_bytes() if "getSolicitudes" in request.url.path
                else (FIXTURE / "decree-1209.pdf").read_bytes())
        return httpx.Response(200, content=body)

    async def run():
        async with _subtel_client(handler) as client:
            return await subtel.fetch_decrees(client)

    rows = asyncio.run(run())
    assert len(rows) == 1
    assert [key for key, _ in registry.successes] == ["subtel"]
    assert registry.failures == []


def test_subtel_error_http_registra_failure(registry):
    def handler(request):
        return httpx.Response(503, content=b"")

    async def run():
        async with _subtel_client(handler) as client:
            return await subtel.fetch_decrees(client)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())
    assert [key for key, _ in registry.failures] == ["subtel"]
    assert registry.successes == []


def test_subtel_documento_invalido_registra_failure(registry):
    def handler(request):
        return httpx.Response(200, content=b"<html><body>sin tabla</body></html>")

    async def run():
        async with _subtel_client(handler) as client:
            return await subtel.fetch_decrees(client)

    with pytest.raises(ValueError, match="Invalid SUBTEL register"):
        asyncio.run(run())
    assert [key for key, _ in registry.failures] == ["subtel"]


# -- fca_nsm ------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _sin_throttle(monkeypatch):
    monkeypatch.setattr(fca_nsm, "_MIN_INTERVAL_S", 0.0)


def test_fca_nsm_busqueda_exito_y_fallo_registran(registry):
    def handler_ok(request):
        return httpx.Response(200, json={"hits": {"total": {"value": 0}, "hits": []}})

    async def run_ok():
        client = fca_nsm.NsmClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler_ok)))
        return await client.list_filings_for_lei("GBQKSY6W7G0OHCQ8OQ72")

    assert asyncio.run(run_ok()) == []
    assert [key for key, _ in registry.successes] == ["fca_nsm"]

    def handler_fail(request):
        return httpx.Response(500, content=b"")

    async def run_fail():
        client = fca_nsm.NsmClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler_fail)))
        return await client.list_filings_for_lei("GBQKSY6W7G0OHCQ8OQ72")

    with pytest.raises(fca_nsm.NsmError):
        asyncio.run(run_fail())
    assert [key for key, _ in registry.failures] == ["fca_nsm"]


def test_fca_nsm_descarga_fallo_registra(registry):
    def handler(request):
        return httpx.Response(404, content=b"")

    filing = SimpleNamespace(url=f"{fca_nsm.NSM_ARTEFACTS_BASE}/x.zip", lei="GBQKSY6W7G0OHCQ8OQ72")

    async def run():
        client = fca_nsm.NsmClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        return await client.fetch_document(filing)

    with pytest.raises(fca_nsm.NsmError):
        asyncio.run(run())
    assert [key for key, _ in registry.failures] == ["fca_nsm"]
    assert registry.successes == []


def test_fca_nsm_guarda_local_no_degrada(registry, monkeypatch):
    """El tope de tamano es una guarda local, no un fallo de la fuente."""
    monkeypatch.setattr(fca_nsm, "MAX_PACKAGE_BYTES", 8)

    def handler(request):
        return httpx.Response(200, content=b"x" * 64)

    filing = SimpleNamespace(url=f"{fca_nsm.NSM_ARTEFACTS_BASE}/x.zip", lei="GBQKSY6W7G0OHCQ8OQ72")

    async def run():
        client = fca_nsm.NsmClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        return await client.fetch_document(filing)

    with pytest.raises(fca_nsm.NsmError, match="no se descarga"):
        asyncio.run(run())
    assert registry.failures == []
    assert registry.successes == []


# -- house_ptr ----------------------------------------------------------------


class _Resp:
    def __init__(self, content=b"DATA", exc=None):
        self.content = content
        self._exc = exc

    def raise_for_status(self):
        if self._exc is not None:
            raise self._exc


class _SyncClient:
    def __init__(self, resp):
        self._resp = resp

    def get(self, url, headers=None):
        return self._resp


def test_house_ptr_exito_y_fallo_registran(registry):
    assert house_ptr._get("https://example.test/x", _SyncClient(_Resp())) == b"DATA"
    assert [key for key, _ in registry.successes] == ["house_ptr"]

    exc = httpx.HTTPStatusError(
        "500", request=httpx.Request("GET", "https://example.test/x"), response=httpx.Response(500)
    )
    with pytest.raises(httpx.HTTPStatusError):
        house_ptr._get("https://example.test/x", _SyncClient(_Resp(exc=exc)))
    assert [key for key, _ in registry.failures] == ["house_ptr"]


def test_house_ptr_guardas_locales_no_degradan(registry):
    """DocID no numerico o ZIP invalido no son fallo de la fuente."""
    with pytest.raises(ValueError, match="DocID"):
        house_ptr.fetch_ptr_pdf(2025, "abc", _SyncClient(_Resp()))
    assert registry.failures == [] and registry.successes == []

    with pytest.raises(Exception):
        house_ptr.fetch_index(2025, _SyncClient(_Resp(content=b"no es un zip")))
    # La descarga fue bien (exito); el ZIP corrupto no degrada la fuente.
    assert registry.failures == []
    assert [key for key, _ in registry.successes] == ["house_ptr"]


# -- official_fx --------------------------------------------------------------

_NBG_JSON = json.dumps([
    {
        "date": "2026-11-06T00:00:00.000Z",
        "currencies": [
            {"code": "EUR", "quantity": 1, "rate": 2.9145, "validFromDate": "2026-11-06T00:00:00.000Z"},
            {"code": "USD", "quantity": 1, "rate": 2.5955, "validFromDate": "2026-11-06T00:00:00.000Z"},
        ],
    }
])


def test_official_fx_exito_y_fallo_registran(registry):
    async def fetcher_ok(url):
        return _NBG_JSON

    quotes, errors = asyncio.run(
        official_fx.fetch_official_quotes(["GEL"], on=date(2026, 11, 6), fetcher=fetcher_ok)
    )
    assert quotes and errors == []
    assert [key for key, _ in registry.successes] == ["official_fx"]
    assert registry.failures == []

    async def fetcher_fail(url):
        raise httpx.ConnectError("sin red")

    quotes, errors = asyncio.run(
        official_fx.fetch_official_quotes(["GEL"], on=date(2026, 11, 6), fetcher=fetcher_fail)
    )
    assert quotes == [] and len(errors) == 1
    assert [key for key, _ in registry.failures] == ["official_fx"]


# -- official_fx: ramas de los parseadores ------------------------------------


def test_positive_descarta_no_numericos_y_no_positivos():
    assert official_fx._positive("abc") is None
    assert official_fx._positive("-5") is None
    assert official_fx._positive("NaN") is None
    assert official_fx._positive("0") is None
    assert official_fx._positive("2.5955") is not None


def test_parse_nbg_errores():
    with pytest.raises(ValueError, match="sin la lista"):
        official_fx.parse_nbg("{}")
    with pytest.raises(ValueError, match="inválidos"):
        official_fx.parse_nbg(json.dumps([{"date": "2026-11-06", "currencies": [
            {"code": "USD", "quantity": 1, "rate": "abc", "validFromDate": "2026-11-06"}]}]))
    with pytest.raises(ValueError, match="sin USD ni EUR"):
        official_fx.parse_nbg(json.dumps([{"date": "2026-11-06", "currencies": [
            {"code": "AMD", "quantity": 1000, "rate": 7.2, "validFromDate": "2026-11-06"}]}]))


def test_parse_cbc_daily_salta_filas_ilegibles_y_exige_tabla():
    html = ('<td data-th="Date"><span>2026/11/06</span></td> <td data-th="NTD/USD"><span>1.2.3</span></td> '
            '<td data-th="Date"><span>2026/11/05</span></td> <td data-th="NTD/USD"><span>32.876</span></td>')
    quotes = official_fx.parse_cbc_daily(html)
    assert len(quotes) == 1 and quotes[0].rate_date == date(2026, 11, 5)
    with pytest.raises(ValueError, match="no está en la página"):
        official_fx.parse_cbc_daily("<table><tr><td>nada</td></tr></table>")


def test_parse_cbc_api_errores():
    with pytest.raises(ValueError, match="sin columna"):
        official_fx.parse_cbc_api(json.dumps(
            {"data": {"structure": {"Table1": [{"data": "DATE"}]}, "dataSets": []}}))
    # Fila corta y sello con formato distinto: se saltan; serie vacia -> error.
    with pytest.raises(ValueError, match="vacía"):
        official_fx.parse_cbc_api(json.dumps({"data": {
            "structure": {"Table1": [{"data": "Date"}, {"data": "NTD/USD"}]},
            "dataSets": [["2026-11-06", "32.8"], ["20261106"]],
        }}))


def test_to_base_rates_sin_pata_no_inventa():
    quote = official_fx.OfficialQuote("TWD", "USD", Decimal("32.8"), date(2026, 11, 6), "CBC", "u")
    assert official_fx.to_base_rates([quote], base_currency="EUR", base_per={}, base_per_date=None) == {}


# -- registro: las 7 claves nuevas existen ------------------------------------


def test_las_siete_claves_nuevas_estan_registradas():
    from app.services.data_source_health import get_data_source_registry

    sources = get_data_source_registry().sources
    expected = {
        "subtel": "SUBTEL",
        "fca_nsm": "FCA NSM",
        "companies_house": "Companies House",
        "official_fx": "NBG Georgia, CBC Taiwán",
        "house_ptr": "House PTR",
        "form13f_dataset": "13F",
        "form_nport_dataset": "N-PORT",
    }
    for key, name_part in expected.items():
        assert key in sources, key
        assert name_part in sources[key].name
        assert sources[key].is_primary is False
        assert sources[key].last_checked_at is None  # nunca sondeada: sin salud afirmada
