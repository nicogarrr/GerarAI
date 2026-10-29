"""Un proveedor externo caído responde 502 controlado, no 500.

El fuzzing (ronda 3) con tickers reales y sin red encontró que
POST /api/companies/{ticker}/refresh/wacc (httpx.ConnectError de FRED) y
POST /api/companies/{ticker}/refresh/yahoo-fundamentals (ConnectionError de
curl_cffi/yfinance) acababan en el handler genérico: 500 «Internal server
error». Ahora: 502 con id de correlación y sin el texto de la excepción.
"""
from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
import requests
from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError
from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import init_db
from app.seed import ensure_company_master
from tests.auth_helpers import auth_settings, signed_request

SECRET = "upstream-network-errors-secret-with-32-chars!!"
LEAK = "query2.finance.yahoo.com"


@pytest.fixture()
def call(monkeypatch):
    init_db()
    ensure_company_master()
    monkeypatch.setattr(auth_module, "get_settings",
                        lambda: auth_settings(strict=True, secret=SECRET, app_env="test"))
    client = TestClient(main.app, raise_server_exceptions=False)
    suffix = uuid4().hex[:8]

    def _call(method: str, path: str):
        return signed_request(client, SECRET, f"t-{suffix}", f"u-{suffix}", method, path)

    return _call


@pytest.mark.parametrize("error", [
    httpx.ConnectError(f"All connection attempts failed https://{LEAK}/?apikey=SECRETO"),
    requests.ConnectionError(f"HTTPSConnectionPool(host='{LEAK}'): apikey=SECRETO"),
    CurlConnectionError(f"Failed to perform, curl: (7) Failed to connect to {LEAK}:443 apikey=SECRETO"),
])
def test_wacc_refresh_with_provider_down_is_502(call, monkeypatch, error):
    from app.api.routes import companies

    async def boom(self, db, company):  # noqa: ARG001
        raise error

    monkeypatch.setattr(companies.WaccInputService, "refresh", boom)
    response = call("POST", "/api/companies/MSFT/refresh/wacc")
    assert response.status_code == 502, response.text
    assert "SECRETO" not in response.text and LEAK not in response.text
    assert "ref:" in response.json()["detail"]


def test_yahoo_fundamentals_refresh_with_yahoo_down_is_502(call, monkeypatch):
    from app.services import yahoo_fundamentals_service

    def boom(db, company):  # noqa: ARG001
        raise CurlConnectionError(f"Failed to perform, curl: (7) Failed to connect to {LEAK}:443")

    monkeypatch.setattr(yahoo_fundamentals_service, "refresh_from_yahoo", boom)
    response = call("POST", "/api/companies/MSFT/refresh/yahoo-fundamentals")
    assert response.status_code == 502, response.text
    assert LEAK not in response.text


def test_other_unhandled_errors_are_still_500(call, monkeypatch):
    from app.api.routes import companies

    async def boom(self, db, company):  # noqa: ARG001
        raise KeyError("bug")

    monkeypatch.setattr(companies.WaccInputService, "refresh", boom)
    response = call("POST", "/api/companies/MSFT/refresh/wacc")
    assert response.status_code == 500
    assert "bug" not in response.text
