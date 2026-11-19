"""Validacion de CIK antes de construir URLs de la SEC (y 422 en la API).

Un CIK no numerico salia a data.sec.gov con ``CIK<basura>.json`` y, segun la
ruta, acababa en 404 poco claro o en un ValueError de ``int()`` DESPUES de la
llamada de red. Ahora ``_pad_cik`` (edgar_common y sec_edgar) falla en local
con un error claro y la API devuelve 422 sin tocar el servicio.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import insider as insider_module
from app.core.database import get_db
from app.services.connectors import edgar_common, sec_edgar

BAD_CIKS = ["123abc", "12345/x", "1/../x", "", "   ", "12345678901", "１２３", "3.14"]


@pytest.mark.parametrize("pad", [edgar_common._pad_cik, sec_edgar._pad_cik], ids=["edgar_common", "sec_edgar"])
class TestPadCik:
    def test_valida_y_rellena(self, pad):
        assert pad("320193") == "0000320193"
        assert pad(320193) == "0000320193"
        assert pad("  320193  ") == "0000320193"
        assert pad("0000320193") == "0000320193"
        assert pad("1") == "0000000001"

    @pytest.mark.parametrize("bad", BAD_CIKS)
    def test_rechaza_no_numericos(self, pad, bad):
        with pytest.raises(ValueError, match="CIK debe ser numerico"):
            pad(bad)


def test_recent_filings_no_sale_a_red_con_cik_basura():
    """La validacion corta ANTES del throttle y del cliente HTTP."""
    from app.services.connectors import form4

    class ExplodingClient:
        def get(self, *a, **kw):  # pragma: no cover - no debe llamarse
            raise AssertionError("no debe salir a red con CIK invalido")

    with pytest.raises(ValueError, match="CIK debe ser numerico"):
        form4.recent_form4_filings("123abc", client=ExplodingClient())


def test_filing_index_url_rechaza_cik_basura():
    with pytest.raises(ValueError):
        edgar_common.filing_index_url("123abc", "0000320193-24-000001")


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(insider_module.router, prefix="/api/insider")

    def _override_db():
        yield object()  # la validacion 422 corta antes de tocar la sesion

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


@pytest.mark.parametrize("bad", ["123abc", "../..", "12345678901", "１２３", "١٢٣"])
def test_api_signals_cik_invalido_da_422(bad):
    """El patron de ruta es [0-9]: digitos Unicode (fullwidth, arabes) dan 422."""
    response = _client().get("/api/insider/signals", params={"ticker": "ACME", "cik": bad})
    assert response.status_code == 422
