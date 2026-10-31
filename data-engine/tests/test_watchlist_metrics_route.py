"""GET /api/watchlist/metrics/{symbol} con response_model.

Forma medida contra la ruta: las cinco ramas de salida devuelven el mismo
envelope de 4 claves (market_cap, per, currency, sources); los huecos sin
base van a null, nunca se fabrica el numero. Servicio real, sin mock.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "watchlist-metrics-secret-"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"watchlist-metrics-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Watchlist metrics test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "watchlist-metrics-user"


def test_metrics_unknown_symbol(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist/metrics/NOPE")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert set(payload) == {"market_cap", "per", "currency", "sources"}
    assert payload["market_cap"] is None
    assert payload["per"] is None
    assert payload["currency"] is None
    assert payload["sources"] == []


def test_metrics_company_without_data(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    # Ticker propio del archivo: la BD de tests es compartida por sesion y otro
    # archivo de watchlist ya siembra ACME (choque UNIQUE en companies.ticker).
    db.add(Company(ticker="ACMX", name="Acme Metrics", exchange="NYSE", currency="USD",
                   company_type="operating", valuation_model="unassigned"))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist/metrics/ACMX")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert set(payload) == {"market_cap", "per", "currency", "sources"}
    # Sin hechos financieros ni precios: huecos a null, divisa de la ficha.
    assert payload["market_cap"] is None
    assert payload["per"] is None
    assert payload["currency"] == "USD"
    assert payload["sources"] == []
