"""/import/commit aplica los mismos topes que POST /transactions.

La vista previa rechaza «1e23», pero el commit recibe las filas desde el cliente
y no las volvía a comprobar: «price: 1e23», «quantity: 1e15» o un NaN entraban
en Transaction (Numeric(20, 6)). En SQLite se guardaba un precio imposible; en
Postgres el INSERT revienta (500). #2606 ya puso estos topes en
POST/PUT /transactions: aquí son los mismos, con 422 antes de tocar la base.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

import main
from app.core.database import init_db
from tests.auth_helpers import csrf_client


@pytest.fixture()
def client():
    init_db()
    return csrf_client(main.app, raise_server_exceptions=False)


def _row(ticker: str, **overrides):
    row = {"row_number": 2, "ticker": ticker, "date": "2024-03-15", "action": "buy",
           "quantity": 10, "price": 12.5, "fees": 0, "currency": "EUR"}
    row.update(overrides)
    return row


def _commit(client, *rows):
    return client.post(
        "/api/portfolio/import/commit",
        json={"transactions": list(rows), "source_filename": "topes.csv"},
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price", 1e23),
        ("price", 1e15),
        ("quantity", 1e15),
        ("fees", 1e19),
        ("price", -1),
        ("fees", -2),
    ],
)
def test_importe_que_no_cabe_da_422(client, field, value):
    ticker = f"ZT{uuid4().hex[:6].upper()}"
    response = _commit(client, _row(ticker, **{field: value}))
    assert response.status_code == 422, (response.status_code, response.text[:300])


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_nan_o_infinito_da_422(client, token):
    # JSON de Python acepta NaN/Infinity: el validador lo rechaza y la
    # respuesta 422 se puede serializar (no repite el valor no finito).
    ticker = f"ZT{uuid4().hex[:6].upper()}"
    body = (
        '{"source_filename": "topes.csv", "transactions": [{"row_number": 2, '
        f'"ticker": "{ticker}", "date": "2024-03-15", "action": "buy", '
        f'"quantity": 10, "price": {token}, "fees": 0, "currency": "EUR"}}]}}'
    )
    response = client.post(
        "/api/portfolio/import/commit",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, (response.status_code, response.text[:300])


def test_una_fila_mala_no_importa_nada_del_lote(client):
    ticker = f"ZT{uuid4().hex[:6].upper()}"
    response = _commit(client, _row(ticker), _row(ticker, row_number=3, price=1e23))
    assert response.status_code == 422, (response.status_code, response.text[:300])
    assert "fila 3" in response.text.lower()
    ok = _commit(client, _row(ticker))
    assert ok.status_code == 200, ok.text[:300]
    assert ok.json()["imported_count"] == 1


def test_importes_grandes_pero_validos_siguen_entrando(client):
    ticker = f"ZT{uuid4().hex[:6].upper()}"
    response = _commit(client, _row(ticker, quantity=1_000_000, price=99999.123456, fees=12.5))
    assert response.status_code == 200, response.text[:300]
    assert response.json()["imported_count"] == 1
