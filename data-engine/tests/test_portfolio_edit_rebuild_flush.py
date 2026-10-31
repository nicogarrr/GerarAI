"""Editar o borrar una operacion debe reconstruir la posicion con los valores NUEVOS.

La sesion trabaja con ``autoflush=False``: si PUT /portfolio/transactions/{id}
reconstruye la posicion sin volcar antes el cambio, la consulta de
``rebuild_position`` lee de la base de datos el ticker y la fecha ANTIGUOS
mientras las cantidades salen del objeto ya modificado en memoria. Resultado
observado en QA: al corregir el ticker de una compra la posicion del ticker
viejo seguia en cartera (valor duplicado) y mover la fecha de una compra
despues de su venta se aceptaba con 200 (venta sin acciones previas).
Ademas, al quitar la ultima compra/venta de una compania (borrado o cambio de
ticker) ``rebuild_position`` salia antes de tocar la Position: quedaba una
posicion fantasma sin ninguna operacion detras.
"""

from uuid import uuid4

import main
from app.core import auth as auth_module
from app.core.database import init_db
from app.seed import seed
from tests.auth_helpers import auth_settings, csrf_client, signed_request

SECRET = "research-edit-rebuild-secret-at-least-32-chars"


def _client(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    seed()
    s = uuid4().hex[:8]
    return csrf_client(main.app), f"edit-{s}", f"user-{s}", s


def _req(client, tenant, user, method, path, body=None):
    return signed_request(client, SECRET, tenant, user, method, path, json_body=body)


def test_cambiar_ticker_mueve_la_posicion_sin_dejar_fantasma(monkeypatch):
    client, tenant, user, s = _client(monkeypatch)
    old, new = f"O{s[:6]}".upper(), f"N{s[:6]}".upper()
    base = {"action": "buy", "quantity": 5, "price": 20,
            "trade_date": "2025-01-10", "currency": "USD"}
    r = _req(client, tenant, user, "POST", "/api/portfolio/transactions", {**base, "ticker": old})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    r = _req(client, tenant, user, "PUT", f"/api/portfolio/transactions/{tid}", {**base, "ticker": new})
    assert r.status_code == 200, r.text

    positions = _req(client, tenant, user, "GET", "/api/portfolio/positions").json()["items"]
    held = {p["ticker"]: p["quantity"] for p in positions}
    assert held == {new: 5.0}


def test_cambiar_ticker_de_una_compra_ya_vendida_se_rechaza(monkeypatch):
    client, tenant, user, s = _client(monkeypatch)
    old, new = f"O{s[:6]}".upper(), f"N{s[:6]}".upper()
    buy = {"ticker": old, "action": "buy", "quantity": 10, "price": 70,
           "trade_date": "2025-01-10", "currency": "USD"}
    r = _req(client, tenant, user, "POST", "/api/portfolio/transactions", buy)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    r = _req(client, tenant, user, "POST", "/api/portfolio/transactions",
             {**buy, "action": "sell", "quantity": 6, "price": 80, "trade_date": "2025-06-10"})
    assert r.status_code == 201, r.text

    r = _req(client, tenant, user, "PUT", f"/api/portfolio/transactions/{tid}", {**buy, "ticker": new})
    # Vender mas de lo comprado: 409 como en POST (3f6ad58 alineo PUT con POST).
    assert r.status_code == 409, r.text

    positions = _req(client, tenant, user, "GET", "/api/portfolio/positions").json()["items"]
    assert {p["ticker"]: p["quantity"] for p in positions} == {old: 4.0}


def test_mover_la_compra_despues_de_su_venta_se_rechaza(monkeypatch):
    client, tenant, user, s = _client(monkeypatch)
    ticker = f"D{s[:6]}".upper()
    buy = {"ticker": ticker, "action": "buy", "quantity": 10, "price": 70,
           "trade_date": "2025-01-10", "currency": "USD"}
    r = _req(client, tenant, user, "POST", "/api/portfolio/transactions", buy)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    r = _req(client, tenant, user, "POST", "/api/portfolio/transactions",
             {**buy, "action": "sell", "quantity": 6, "price": 80, "trade_date": "2025-06-10"})
    assert r.status_code == 201, r.text

    r = _req(client, tenant, user, "PUT", f"/api/portfolio/transactions/{tid}",
             {**buy, "trade_date": "2025-07-10"})
    assert r.status_code == 409, r.text

    transactions = _req(client, tenant, user, "GET", "/api/portfolio/transactions").json()["items"]
    stored = next(t for t in transactions if t["id"] == tid)
    assert stored["trade_date"] == "2025-01-10"


def test_cambiar_fecha_valida_actualiza_la_primera_compra(monkeypatch):
    client, tenant, user, s = _client(monkeypatch)
    ticker = f"F{s[:6]}".upper()
    buy = {"ticker": ticker, "action": "buy", "quantity": 3, "price": 50,
           "trade_date": "2025-01-10", "currency": "USD"}
    r = _req(client, tenant, user, "POST", "/api/portfolio/transactions", buy)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    r = _req(client, tenant, user, "PUT", f"/api/portfolio/transactions/{tid}",
             {**buy, "trade_date": "2025-03-03"})
    assert r.status_code == 200, r.text

    position = next(
        p for p in _req(client, tenant, user, "GET", "/api/portfolio/positions").json()["items"]
        if p["ticker"] == ticker
    )
    assert position["first_buy_date"] == "2025-03-03"


def test_borrar_la_unica_operacion_borra_la_posicion(monkeypatch):
    client, tenant, user, s = _client(monkeypatch)
    ticker = f"X{s[:6]}".upper()
    r = _req(client, tenant, user, "POST", "/api/portfolio/transactions",
             {"ticker": ticker, "action": "buy", "quantity": 100, "price": 2,
              "trade_date": "2025-01-10", "currency": "USD"})
    assert r.status_code == 201, r.text

    r = _req(client, tenant, user, "DELETE", f"/api/portfolio/transactions/{r.json()['id']}")
    assert r.status_code == 204, r.text

    positions = _req(client, tenant, user, "GET", "/api/portfolio/positions").json()["items"]
    assert ticker not in {p["ticker"] for p in positions}
