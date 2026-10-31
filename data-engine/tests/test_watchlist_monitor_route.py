"""GET /api/watchlist/monitor con response_model.

Forma medida contra la ruta y fair_value_service.choose/_reading: item de 18
claves siempre; los huecos sin dato van a null, nunca se omiten. Sin tesis ni
motor: fair_value_source None y label "Sin valor justo". earnings_status str.
Servicio real sobre SQLite, sin mock.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "watchlist-monitor-secret-"

ITEM_KEYS = {
    "low_52w", "low_52w_date", "low_52w_sessions", "last_close", "last_close_date",
    "fair_value", "fair_value_thesis_version", "fair_value_source", "fair_value_label",
    "fair_value_as_of", "fair_value_publishable", "fair_value_reason", "valuation_side",
    "currency", "next_earnings_date", "next_earnings_source", "next_earnings_confirmed",
}


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"watchlist-monitor-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Watchlist monitor test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "watchlist-monitor-user"


def test_monitor_unknown_ticker_empty_items(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist/monitor", params={"tickers": "NOPE"})

    assert res.status_code == 200, res.text
    payload = res.json()
    assert set(payload) == {"items", "earnings_status"}
    assert payload["items"] == {}
    assert isinstance(payload["earnings_status"], str)


def test_monitor_company_without_data_18_keys(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    db.add(Company(ticker="ACME", name="Acme", exchange="NYSE", currency="USD", company_type="operating", valuation_model="unassigned"))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist/monitor", params={"tickers": "ACME"})

    assert res.status_code == 200, res.text
    item = res.json()["items"]["ACME"]
    # 18 claves siempre, nunca omitidas.
    assert set(item) == ITEM_KEYS
    # Sin precios, sin tesis ni motor: huecos a null y «Sin valor justo».
    assert item["low_52w"] is None
    assert item["low_52w_sessions"] == 0
    assert item["last_close"] is None
    assert item["fair_value"] is None
    assert item["fair_value_source"] is None
    assert item["fair_value_label"] == "Sin valor justo"
    assert item["fair_value_publishable"] is False
    assert item["valuation_side"] is None
    assert item["currency"] == "USD"
    assert item["next_earnings_date"] is None
