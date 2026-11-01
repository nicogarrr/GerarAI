"""Topes de tamano en la importacion IBKR (Flex XML / CSV de actividad).

Antes del fix, ``IBKRXmlImportRequest.xml`` y ``IBKRCsvImportRequest.csv``
solo tenian ``min_length``: un body gigante se leia y parseaba entero en
memoria (mismo vector de DoS que /import/file, acotado en el PR hermano).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.portfolio import MAX_IBKR_IMPORT_BYTES
from app.api.routes.portfolio import router as portfolio_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(portfolio_router, prefix="/api/portfolio")
    return TestClient(app, raise_server_exceptions=False)


def test_ibkr_xml_over_limit_rejected_422():
    resp = _client().post(
        "/api/portfolio/import/ibkr/xml",
        json={"xml": "<FlexQueryResponse>" + "a" * MAX_IBKR_IMPORT_BYTES + "</FlexQueryResponse>"},
    )
    assert resp.status_code == 422


def test_ibkr_csv_over_limit_rejected_422():
    resp = _client().post(
        "/api/portfolio/import/ibkr/csv",
        json={"csv": "a" * (MAX_IBKR_IMPORT_BYTES + 1)},
    )
    assert resp.status_code == 422
