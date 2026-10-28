"""Rutas de cartera sin cobertura: PATCH /prices, DELETE /holdings y DELETE de
transacciones que no son compra/venta.

Cobertura (oct-2026): app/api/routes/portfolio.py dejaba sin ejercitar el 404 y
el 409 de PATCH /prices, todo DELETE /holdings/{ticker} y el 404 de borrar una
transaccion que no es buy/sell. Son rutas que cambian dinero: un 200 silencioso
o un borrado que cruza tenants seria un bug grave.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Position, Transaction
from app.seed import seed
from tests.auth_helpers import auth_settings, signed_request

SECRET = "research-portfolio-route-gaps-secret-32-chars"


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET))
    init_db()
    seed()
    suffix = uuid4().hex[:8]
    client = TestClient(main.app, raise_server_exceptions=False)
    tenant, user = f"prg-{suffix}", f"user-{suffix}"
    ticker = f"P{suffix[:6]}".upper()

    def call(method, path, json_body=None, *, as_tenant=None):
        t = as_tenant or tenant
        return signed_request(client, SECRET, t, f"u-{t}", method, path, json_body=json_body)

    def buy(qty=10, price=5, day="2026-01-02", action="buy", t=None):
        r = call("POST", "/api/portfolio/transactions",
                 {"ticker": ticker, "action": action, "quantity": qty, "price": price, "trade_date": day},
                 as_tenant=t)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    return {"call": call, "buy": buy, "ticker": ticker, "tenant": tenant}


def _position(ticker: str, tenant: str) -> Position | None:
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == ticker))
        if company is None:
            return None
        from app.models import Tenant  # import local: el modelo solo hace falta aqui

        t = db.scalar(select(Tenant).where(Tenant.external_id == tenant))
        return db.scalar(select(Position).where(Position.company_id == company.id, Position.tenant_id == t.id))
    finally:
        db.close()


def test_patch_price_actualiza_valor_y_plusvalia(ctx):
    ctx["buy"](qty=10, price=5)
    r = ctx["call"]("PATCH", "/api/portfolio/prices", {"ticker": ctx["ticker"].lower(), "price": "7.5", "as_of": "2026-02-02"})
    assert r.status_code == 200, r.text
    assert r.json() == {"ticker": ctx["ticker"], "market_price": 7.5}
    pos = _position(ctx["ticker"], ctx["tenant"])
    assert pos.market_value == Decimal("75")
    assert pos.unrealized_pnl == Decimal("25")
    assert str(pos.as_of) == "2026-02-02"


def test_patch_price_de_ticker_desconocido_es_404(ctx):
    r = ctx["call"]("PATCH", "/api/portfolio/prices", {"ticker": "NOEXISTE" + uuid4().hex[:4], "price": "1"})
    assert r.status_code == 404


def test_patch_price_sin_posicion_propia_es_404_y_no_toca_la_ajena(ctx):
    """Otro tenant con la misma empresa no puede reescribir el precio de mi posicion."""
    ctx["buy"](qty=10, price=5)
    other = f"otro-{uuid4().hex[:8]}"
    r = ctx["call"]("PATCH", "/api/portfolio/prices", {"ticker": ctx["ticker"], "price": "999"}, as_tenant=other)
    assert r.status_code == 404
    pos = _position(ctx["ticker"], ctx["tenant"])
    assert pos.market_price != Decimal("999")


@pytest.mark.parametrize("price", ["0", "-3"])
def test_patch_price_no_positivo_es_422(ctx, price):
    ctx["buy"]()
    r = ctx["call"]("PATCH", "/api/portfolio/prices", {"ticker": ctx["ticker"], "price": price})
    assert r.status_code == 422


def test_patch_price_con_valoracion_suspendida_es_409_y_no_cambia_nada(ctx):
    ctx["buy"](qty=10, price=5)
    pos = _position(ctx["ticker"], ctx["tenant"])
    db = SessionLocal()
    try:
        row = db.get(Position, pos.id)
        row.valuation_hold_reason = "split pendiente de revisar"
        before = row.market_price
        db.commit()
    finally:
        db.close()
    r = ctx["call"]("PATCH", "/api/portfolio/prices", {"ticker": ctx["ticker"], "price": "50"})
    assert r.status_code == 409
    assert "split pendiente" in r.json()["detail"]
    assert _position(ctx["ticker"], ctx["tenant"]).market_price == before


def test_delete_holding_borra_transacciones_y_posicion(ctx):
    ctx["buy"](qty=10, price=5)
    ctx["buy"](qty=2, price=6, day="2026-01-03")
    r = ctx["call"]("DELETE", f"/api/portfolio/holdings/{ctx['ticker']}")
    assert r.status_code == 204, r.text
    assert _position(ctx["ticker"], ctx["tenant"]) is None
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == ctx["ticker"]))
        legs = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.company_id == company.id))
    finally:
        db.close()
    assert legs == 0
    # Borrar otra vez: ya no existe.
    assert ctx["call"]("DELETE", f"/api/portfolio/holdings/{ctx['ticker']}").status_code == 404


def test_delete_holding_no_borra_la_del_otro_tenant(ctx):
    ctx["buy"](qty=10, price=5)
    other = f"otro-{uuid4().hex[:8]}"
    ctx["buy"](qty=3, price=5, t=other)
    r = ctx["call"]("DELETE", f"/api/portfolio/holdings/{ctx['ticker']}", as_tenant=other)
    assert r.status_code == 204
    mine = _position(ctx["ticker"], ctx["tenant"])
    assert mine is not None and mine.quantity == Decimal("10")


def test_delete_holding_de_ticker_desconocido_es_404(ctx):
    assert ctx["call"]("DELETE", "/api/portfolio/holdings/ZZNONE" + uuid4().hex[:3]).status_code == 404


def test_delete_transaccion_inexistente_es_404(ctx):
    assert ctx["call"]("DELETE", "/api/portfolio/transactions/987654321").status_code == 404


def test_delete_venta_reconstruye_la_posicion(ctx):
    ctx["buy"](qty=10, price=5)
    sell = ctx["buy"](qty=4, price=6, day="2026-01-05", action="sell")
    assert _position(ctx["ticker"], ctx["tenant"]).quantity == Decimal("6")
    assert ctx["call"]("DELETE", f"/api/portfolio/transactions/{sell}").status_code == 204
    assert _position(ctx["ticker"], ctx["tenant"]).quantity == Decimal("10")


def test_delete_unica_compra_elimina_la_posicion(ctx):
    only = ctx["buy"](qty=10, price=5)
    assert ctx["call"]("DELETE", f"/api/portfolio/transactions/{only}").status_code == 204
    assert _position(ctx["ticker"], ctx["tenant"]) is None
