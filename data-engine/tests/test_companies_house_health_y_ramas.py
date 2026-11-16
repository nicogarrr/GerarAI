"""Companies House: salud registrada y ramas de guarda (fix7b)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.services.connectors import companies_house as ch


class _Registry:
    def __init__(self):
        self.successes = []
        self.failures = []

    def record_success(self, key, elapsed_ms=0.0):
        self.successes.append((key, elapsed_ms))

    def record_failure(self, key, error):
        self.failures.append((key, error))


@pytest.fixture
def registry(monkeypatch):
    reg = _Registry()
    monkeypatch.setattr(ch, "get_data_source_registry", lambda: reg)
    return reg


def _client(handler, **kw):
    return ch.CompaniesHouseClient("k", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)


def test_exito_registra_success(registry):
    def handler(request):
        return httpx.Response(200, json={"items": []})

    async def run():
        c = _client(handler)
        assert await c.filing_history("00000001") == []

    asyncio.run(run())
    assert [k for k, _ in registry.successes] == ["companies_house"]
    assert registry.failures == []


def test_404_neutro_no_toca_el_registro(registry):
    """No degradar no es sanar: un 404 no suma exito ni resetea fallos previos."""
    registry.failures.extend([("companies_house", "HTTP 500")] * 3)

    def handler(request):
        return httpx.Response(404)

    async def run():
        c = _client(handler)
        assert await c.filing_history("00000001") == []

    asyncio.run(run())
    assert registry.successes == []
    assert registry.failures == [("companies_house", "HTTP 500")] * 3


@pytest.mark.parametrize("status", [500, 401, 403])
def test_error_http_degrada(registry, status):
    def handler(request):
        return httpx.Response(status)

    async def run():
        await _client(handler)._json("/company/00000001")

    with pytest.raises(ch.CompaniesHouseError):
        asyncio.run(run())
    assert [k for k, _ in registry.failures] == ["companies_house"]


def test_error_de_red_degrada(registry):
    def handler(request):
        raise httpx.ConnectError("sin red")

    async def run():
        await _client(handler)._json("/company/00000001")

    with pytest.raises(httpx.ConnectError):
        asyncio.run(run())
    assert [k for k, _ in registry.failures] == ["companies_house"]


def test_429_degrada_y_agota_presupuesto(registry):
    def handler(request):
        return httpx.Response(429)

    async def run():
        await _client(handler)._json("/company/00000001")

    with pytest.raises(ch.CompaniesHouseBudgetExceeded):
        asyncio.run(run())
    assert [k for k, _ in registry.failures] == ["companies_house"]


# -- guardas locales: no degradan ----------------------------------------------


def test_guardas_locales_no_degradan(registry):
    async def run():
        # Sin clave: guarda local.
        with pytest.raises(ValueError):
            ch.CompaniesHouseClient("")
        # Presupuesto de peticiones agotado: guarda local.
        c = _client(lambda r: httpx.Response(200, json={}), max_requests=0)
        with pytest.raises(ch.CompaniesHouseBudgetExceeded):
            await c._json("/x")
        # Ventana de ritmo saturada: guarda local.
        ventana = SimpleNamespace(wait_seconds=lambda now: 100.0, record=lambda now: None)
        c2 = _client(lambda r: httpx.Response(200, json={}), window=ventana)
        with pytest.raises(ch.CompaniesHouseBudgetExceeded):
            await c2._json("/x")
        # Rutas/host no reconocidos: guardas locales.
        with pytest.raises(ch.CompaniesHouseError):
            await c.officer_appointments("/otra/ruta")
        with pytest.raises(ch.CompaniesHouseError):
            await c.document_metadata("https://evil.invalid/doc")
        with pytest.raises(ch.CompaniesHouseError):
            await c.document_content({"links": {"document": "https://evil.invalid/d"}}, "application/pdf")

    asyncio.run(run())
    assert registry.failures == [] and registry.successes == []


# -- ramas ---------------------------------------------------------------------


def test_url_publicas():
    assert ch.public_document_url("00000001", "TX1").endswith("/document?format=pdf&download=0")
    assert ch.public_document_url("00000001", "TX1", fmt="xml").endswith("format=xml&download=0")


def test_aclose_cierra_cliente_propio():
    cerrado = []

    class Propio:
        async def aclose(self):
            cerrado.append(True)

    c = ch.CompaniesHouseClient("k")
    c._client = Propio()
    asyncio.run(c.aclose())
    assert cerrado == [True]


def test_json_no_json_y_no_dict():
    def handler(request):
        if "lista" in request.url.path:
            return httpx.Response(200, json=[1, 2])
        return httpx.Response(200, content=b"no json", headers={"content-type": "text/plain"})

    async def run():
        c = _client(handler)
        with pytest.raises(ch.CompaniesHouseError, match="no JSON"):
            await c._json("/company/1")
        assert await c._json("/lista") is None

    asyncio.run(run())


def test_document_content_redireccion_y_limites():
    destino = "https://s3.example/firmado.pdf"

    def handler(request):
        if str(request.url) == destino:
            return httpx.Response(200, content=b"PDF")
        return httpx.Response(302, headers={"location": destino})

    metadata = {"links": {"document": f"https://{ch.DOCUMENT_API_HOST}/document/x"}}

    async def run():
        c = _client(handler)
        assert await c.document_content(metadata, "application/pdf") == b"PDF"

    asyncio.run(run())

    def handler_fail(request):
        if str(request.url) == destino:
            return httpx.Response(403, content=b"")
        return httpx.Response(302, headers={"location": destino})

    async def run_fail():
        c = _client(handler_fail)
        with pytest.raises(ch.CompaniesHouseError, match="documento 403"):
            await c.document_content(metadata, "application/pdf")

    asyncio.run(run_fail())

    def handler_big(request):
        return httpx.Response(200, content=b"x" * 10)

    async def run_big():
        c = _client(handler_big)
        with pytest.raises(ch.CompaniesHouseError, match="grande"):
            await c.document_content(metadata, "application/pdf", max_bytes=3)

    asyncio.run(run_big())


def test_throttle_espera_cuando_la_ventana_lo_pide(monkeypatch):
    dormido = []

    async def fake_sleep(seconds):
        dormido.append(seconds)

    monkeypatch.setattr(ch.asyncio, "sleep", fake_sleep)
    ventana = SimpleNamespace(wait_seconds=lambda now: 0.5, record=lambda now: None)

    async def run():
        c = _client(lambda r: httpx.Response(200, json={}), window=ventana)
        await c._json("/x")

    asyncio.run(run())
    assert dormido == [0.5]
