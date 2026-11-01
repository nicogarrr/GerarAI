"""El PDF de cartera marca las posiciones sin cotización real.

Sin cotización guardada, el ledger valora la posición con el precio de su
última operación (auditoría A3, #3980). /positions ya la rotula «sin
cotización real», pero el informe PDF solo miraba ``market_price == 0``: con
el precio de la operación lo presentaba como una cotización de mercado, sin
asterisco ni limitación.
"""

import io
from uuid import uuid4

from fastapi.testclient import TestClient
from pypdf import PdfReader

import main
from app.core import auth as auth_module
from app.core.database import init_db
from tests.auth_helpers import auth_settings, signed_request

SECRET = "research-pdf-quote-missing-secret-32-chars-x"


def _client(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    suffix = uuid4().hex[:8]
    return TestClient(main.app, raise_server_exceptions=False), f"pdfq-{suffix}", f"user-{suffix}"


def _pdf_text(client, tenant, user) -> str:
    portfolios = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio")
    assert portfolios.status_code == 200, portfolios.text
    portfolio_id = next(p["id"] for p in portfolios.json() if p["is_default"])
    response = signed_request(client, SECRET, tenant, user, "GET", f"/api/portfolio/{portfolio_id}/pdf")
    assert response.status_code == 200, response.text
    reader = PdfReader(io.BytesIO(response.content))
    return "\n".join(page.extract_text() for page in reader.pages)


def test_pdf_marca_posicion_valorada_con_su_ultima_operacion(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    ticker = f"PQM{uuid4().hex[:5]}".upper()
    response = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
        json_body={
            "ticker": ticker, "action": "buy", "quantity": "3", "price": "12.5",
            "currency": "EUR", "trade_date": "2024-02-01",
        },
    )
    assert response.status_code == 201, response.text
    positions = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/positions")
    position = {p["ticker"]: p for p in positions.json()["items"]}[ticker]
    assert position["quote_missing"] is True

    text = _pdf_text(client, tenant, user)
    assert "12.50 EUR *" in text
    assert "sin cotización" in text


def test_pdf_no_marca_posicion_con_cotizacion(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    ticker = f"PQC{uuid4().hex[:5]}".upper()
    response = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
        json_body={
            "ticker": ticker, "action": "buy", "quantity": "3", "price": "12.5",
            "currency": "EUR", "trade_date": "2024-02-01",
        },
    )
    assert response.status_code == 201, response.text
    response = signed_request(
        client, SECRET, tenant, user, "PATCH", "/api/portfolio/prices",
        json_body={"ticker": ticker, "price": 20, "as_of": "2024-03-01"},
    )
    assert response.status_code == 200, response.text

    text = _pdf_text(client, tenant, user)
    assert "20.00 EUR" in text
    assert "20.00 EUR *" not in text
    assert "sin cotización" not in text.lower()
