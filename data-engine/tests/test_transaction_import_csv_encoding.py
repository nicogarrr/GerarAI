"""Importar operaciones: CSV en UTF-16 y CSV mal formado sin error 500.

Excel guarda «Texto Unicode» en UTF-16 con BOM y separado por tabuladores.
Ese archivo se decodificaba como Latin-1, el lector CSV tropezaba con los
bytes nulos y su ``csv.Error`` (que no es ``ValueError``) se escapaba de la
ruta como 500. Lo mismo con «CSV (Macintosh)» de Excel para Mac (filas
acabadas en \r): el lector se abría sin ``newline=""``. Ahora los dos se leen
bien y un CSV que el lector no pueda partir responde 400 en español.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.portfolio import router as portfolio_router
from app.services.ibkr_import_service import IBKRImportError, _csv_rows

ROWS = "Fecha\tSímbolo\tOperación\tCantidad\tPrecio\tComisión\tDivisa\r\n29/10/2026\tSAN.MC\tCompra\t100\t3,5\t1,5\tEUR\r\n"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(portfolio_router, prefix="/api/portfolio")
    return TestClient(app, raise_server_exceptions=False)


def test_utf16_unicode_text_from_excel_is_read():
    response = _client().post(
        "/api/portfolio/import/file",
        files={"file": ("operaciones.csv", ROWS.encode("utf-16"), "text/csv")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["detected_columns"]["ticker"] == "Símbolo"
    assert body["valid_rows_count"] == 1


def test_mac_csv_with_cr_line_endings_is_read():
    # Excel para Mac, «CSV (Macintosh)»: las filas acaban en \r a secas.
    content = ROWS.replace("\t", ";").replace("\r\n", "\r").encode("utf-8")
    response = _client().post(
        "/api/portfolio/import/file",
        files={"file": ("operaciones.csv", content, "text/csv")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["valid_rows_count"] == 1


def test_unparseable_csv_is_a_400_not_a_500():
    # Un campo de más de 128 KB supera el límite del lector CSV.
    content = b"Fecha,Ticker,Cantidad\n29/10/2026," + b"X" * 200_000 + b",1\n"
    response = _client().post(
        "/api/portfolio/import/file",
        files={"file": ("operaciones.csv", content, "text/csv")},
    )
    assert response.status_code == 400, response.text
    assert "CSV" in response.json()["detail"]


def test_ibkr_activity_csv_with_cr_line_endings_and_bad_csv():
    assert _csv_rows("Symbol,Quantity\rAAPL,1\r") == [["Symbol", "Quantity"], ["AAPL", "1"]]
    with pytest.raises(IBKRImportError, match="CSV"):
        _csv_rows("Symbol,Quantity\nAAPL," + "X" * 200_000 + "\n")
