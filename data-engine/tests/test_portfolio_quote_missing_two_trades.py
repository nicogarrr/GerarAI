"""Sin cotización real, una segunda operación no deja la cartera valorada con la primera.

rebuild_position valora con el precio de la última operación cuando nunca se
guardó una cotización (auditoría A3), pero en la siguiente operación conservaba
ese precio como si fuera una cotización: con compras a 10 y a 14, la posición
seguía valorada a 10 y, como 10 ya no era el precio de la última operación,
/positions dejaba de marcarla «sin cotización» y enseñaba una pérdida inventada.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import main
from app.api.routes.portfolio import _trade_price_fallbacks
from app.core import auth as auth_module
from app.core.database import init_db
from app.models import MarketPrice
from app.models.entities import Base
from app.services.portfolio_ledger_service import PortfolioLedgerService
from tests.auth_helpers import auth_settings, signed_request

SECRET = "research-quote-missing-two-trades-secret-32chars"


def _client(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    suffix = uuid4().hex[:8]
    tenant, user = f"qm2-{suffix}", f"user-{suffix}"
    return TestClient(main.app, raise_server_exceptions=False), tenant, user


def _trade(client, tenant, user, ticker, action, quantity, price, trade_date):
    response = signed_request(
        client, SECRET, tenant, user, "POST", "/api/portfolio/transactions",
        json_body={
            "ticker": ticker, "action": action, "quantity": quantity, "price": price,
            "currency": "EUR", "trade_date": trade_date,
        },
    )
    assert response.status_code == 201, response.text


def _position(client, tenant, user, ticker):
    response = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/positions")
    assert response.status_code == 200, response.text
    return {p["ticker"]: p for p in response.json()["items"]}[ticker]


def _assert_unknown_pnl(position):
    assert position["quote_missing"] is True
    for key in ("unrealized_pnl", "unrealized_pnl_native", "unrealized_pnl_base"):
        assert position[key] is None, key


def test_segunda_compra_sin_cotizacion_valora_con_la_ultima(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    ticker = f"NQ2{uuid4().hex[:5]}".upper()
    _trade(client, tenant, user, ticker, "buy", "2", "10", "2024-01-02")
    _trade(client, tenant, user, ticker, "buy", "2", "14", "2024-06-03")
    position = _position(client, tenant, user, ticker)
    assert position["market_price"] == 14.0
    assert position["market_value"] == 56.0
    assert position["as_of"] == "2024-06-03"
    _assert_unknown_pnl(position)


def test_venta_sin_cotizacion_valora_con_su_precio(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    ticker = f"NQS{uuid4().hex[:5]}".upper()
    _trade(client, tenant, user, ticker, "buy", "4", "10", "2024-01-02")
    _trade(client, tenant, user, ticker, "sell", "1", "15", "2024-06-03")
    position = _position(client, tenant, user, ticker)
    assert position["market_price"] == 15.0
    assert position["market_value"] == 45.0
    _assert_unknown_pnl(position)


def test_precio_manual_se_conserva_tras_otra_compra(monkeypatch):
    client, tenant, user = _client(monkeypatch)
    ticker = f"NQM{uuid4().hex[:5]}".upper()
    _trade(client, tenant, user, ticker, "buy", "2", "10", "2024-01-02")
    response = signed_request(
        client, SECRET, tenant, user, "PATCH", "/api/portfolio/prices",
        json_body={"ticker": ticker, "price": "12"},
    )
    assert response.status_code == 200, response.text
    _trade(client, tenant, user, ticker, "buy", "2", "14", "2024-06-03")
    position = _position(client, tenant, user, ticker)
    assert position["market_price"] == 12.0
    assert position["quote_missing"] is False
    assert position["unrealized_pnl"] == 48.0 - 48.0


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _buy(service, db, price, trade_date):
    return service.create_transaction(
        db, ticker="OLDQ", action="buy", quantity=Decimal("2"), price=Decimal(price),
        trade_date=trade_date, currency="EUR",
    )


def test_precio_de_una_operacion_anterior_sin_cotizacion_es_respaldo(db):
    """Filas ya guardadas con el precio de la primera compra se marcan igual."""
    service = PortfolioLedgerService()
    _buy(service, db, "10", date(2024, 1, 2))
    _buy(service, db, "14", date(2024, 6, 3))
    company = service.ensure_company(db, "OLDQ")
    position = service.rebuild_position(db, company.id)
    position.market_price = Decimal("10")  # como lo dejaba el rebuild anterior
    db.flush()
    assert _trade_price_fallbacks(db, [position]) == {company.id}

    db.add(MarketPrice(company_id=company.id, date=date(2024, 7, 1), close=Decimal("10")))
    db.flush()
    assert _trade_price_fallbacks(db, [position]) == set()
