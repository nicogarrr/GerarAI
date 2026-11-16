"""GET /api/watchlist/new-13f: nuevas posiciones institucionales (13F) por
empresa de la watchlist del tenant firmado.

Agregación compacta sobre institutional_holders (lectura de datos guardados,
sin red): un item por watch item del tenant; sin snapshot -> status sin_datos
con motivo, nunca una lista inventada.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant, WatchItem
from app.services import institutional_holders as ih
from tests.auth_helpers import auth_settings, signed_request
from tests.test_institutional_new_positions import parsed_pair

SECRET = "watchlist-new13f-secret-"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"watchlist-new13f-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Watchlist new 13F test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "watchlist-new13f-user"


def _seed(tenant_ext: str, symbols: list[str]) -> None:
    db = SessionLocal()
    tenant = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    for symbol in symbols:
        db.add(WatchItem(tenant_id=tenant.id, symbol=symbol))
    db.commit()
    db.close()


def _ingest_apple() -> None:
    db = SessionLocal()
    if db.query(Company).filter(Company.ticker == "AAPL").first() is None:
        db.add(
            Company(
                ticker="AAPL",
                name="Apple",
                exchange="NASDAQ",
                company_type="mature",
                valuation_model="dcf",
                isin="US0378331005",
            )
        )
        db.commit()
    # Idempotente por checksum (tests.test_institutional_holders).
    ih.ingest_parsed(db, parsed_pair(), ["new13f", "old13f"], ih.universe_cusips(db))
    db.close()


def test_new_13f_items_per_watchlist_ticker(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    _ingest_apple()
    _seed(tenant, ["AAPL", "ZZSINTRECEF"])

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist/new-13f")
    assert res.status_code == 200, res.text
    items = {item["ticker"]: item for item in res.json()["items"]}
    assert set(items) == {"AAPL", "ZZSINTRECEF"}

    aapl = items["AAPL"]
    assert aapl["status"] == "ok"
    assert aapl["period"] == "2026-06-30"
    np = aapl["new_positions"]
    assert np["status"] == "ok"
    assert np["count"] == 14
    assert np["top_by_shares"][0]["cik"] == "0000000014"
    assert np["top_by_shares"][0]["shares"] == 14
    assert np["top_by_value"][0]["value_usd"] == 990

    # Sin snapshot: ausencia declarada, nunca lista inventada.
    missing = items["ZZSINTRECEF"]
    assert missing["status"] == "sin_datos"
    assert missing["new_positions"] is None


def test_new_13f_only_returns_own_tenant(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    _ingest_apple()
    _seed(tenant, ["AAPL"])
    other_ext = f"watchlist-new13f-otro-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=other_ext, name="Otro tenant"))
    db.commit()
    db.close()
    _seed(other_ext, ["ZZOTRO"])

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist/new-13f")
    assert res.status_code == 200, res.text
    tickers = [item["ticker"] for item in res.json()["items"]]
    assert tickers == ["AAPL"]
