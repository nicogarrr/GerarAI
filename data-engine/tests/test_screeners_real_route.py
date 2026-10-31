"""GET /api/screeners/metric-coverage y /real con response_model.

Envelope de /real medido contra _real_response_payload (7 claves siempre);
item medido contra el builder de _refetch_real_items (21 claves siempre;
huecos del proveedor a null; beta siempre null en el codigo medido). Vendor
"offline" (fixture determinista del propio codigo, sin red); el item se siembra
en la cache LKG del tenant con la forma medida y el test fija que el wire la
conserva entera (un modelo parcial borraria claves).
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.api.routes import screeners as screeners_module
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "screeners-real-secret-"

ITEM_KEYS = {
    "symbol", "name", "price", "priceAsOf", "priceTimestampKind", "priceDate",
    "currency", "change", "changePercent", "marketCap", "volume", "prevClose",
    "sector", "exchange", "type", "pe", "pb", "roe", "has_fundamentals", "beta",
}


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    monkeypatch.setattr(
        screeners_module,
        "get_settings",
        lambda: SimpleNamespace(
            screener_quote_vendor="offline", is_production=False, finnhub_api_key=None,
        ),
    )
    init_db()
    tenant_ext = f"screeners-real-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Screeners real test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "screeners-real-user"


def _tenant_pk(tenant_ext: str) -> int:
    db = SessionLocal()
    tenant = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.close()
    return tenant.id


def test_metric_coverage_envelope(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/screeners/metric-coverage")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert set(payload) == {"metrics_with_data"}
    assert isinstance(payload["metrics_with_data"], list)
    assert all(isinstance(m, str) for m in payload["metrics_with_data"])


def test_real_empty_universe_envelope(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/screeners/real")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert set(payload) == {
        "source", "as_of", "count", "screener", "refreshing", "unavailable", "universe_size",
    }
    # Vendor offline: sin items; unavailable true (no es un filtro vacio).
    assert payload["source"] == "offline"
    assert payload["screener"] == []
    assert payload["count"] == 0
    assert payload["unavailable"] is True
    assert isinstance(payload["refreshing"], bool)
    assert isinstance(payload["as_of"], (int, float))
    assert payload["universe_size"] >= 1


def test_real_cached_item_keeps_21_keys(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    tenant_pk = _tenant_pk(tenant)
    item = {
        "symbol": "AAPL", "name": "Apple", "price": 10.5, "priceAsOf": 1_730_000_000.0,
        "priceTimestampKind": "quote", "priceDate": "2026-10-31", "currency": "USD",
        "change": 0.5, "changePercent": 5.0, "marketCap": 1_000_000.0, "volume": 1000.0,
        "prevClose": 10.0, "sector": "Information Technology", "exchange": "US",
        "type": "Stock", "pe": None, "pb": None, "roe": None,
        "has_fundamentals": False, "beta": None,
    }
    screeners_module._store_real_items([item], "offline", tenant_pk)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/screeners/real")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["unavailable"] is False
    assert payload["count"] == 1
    wire_item = payload["screener"][0]
    # El wire conserva las 21 claves medidas: ni una borrada ni una anadida.
    assert set(wire_item) == ITEM_KEYS
    assert wire_item["symbol"] == "AAPL"
    assert wire_item["beta"] is None
    assert wire_item["pe"] is None
