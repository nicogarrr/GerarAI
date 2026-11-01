import time
from uuid import uuid4

from sqlalchemy import delete, select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant, WatchItem
from app.seed import seed
from tests.auth_helpers import auth_settings, csrf_client, signed_request


def _cleanup(watch_symbols: list[str], tenant_external_ids: list[str] | None = None) -> None:
    db = SessionLocal()
    try:
        items = db.scalars(
            select(WatchItem).where(WatchItem.symbol.in_(watch_symbols))
        ).all()
        for item in items:
            db.delete(item)
        if tenant_external_ids:
            tenant_ids = db.scalars(
                select(Tenant.id).where(Tenant.external_id.in_(tenant_external_ids))
            ).all()
            if tenant_ids:
                db.execute(delete(WatchItem).where(WatchItem.tenant_id.in_(tenant_ids)))
                db.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
        db.commit()
    finally:
        db.close()


def test_watchlist_crud_and_deduplication():
    init_db()
    symbols = ["MSFT", "AAPL", "WLTEST", "WLTEST2"]
    _cleanup(symbols)
    client = csrf_client(main.app)

    created = client.post(
        "/api/watchlist", json={"symbol": "msft", "company": "Microsoft"}
    )
    assert created.status_code == 201
    assert created.json()["symbol"] == "MSFT"
    assert created.json()["company"] == "Microsoft"
    first_id = created.json()["id"]

    # Dedup: same symbol upserts instead of duplicating.
    duplicated = client.post(
        "/api/watchlist", json={"symbol": "MSFT", "company": "Microsoft Corp."}
    )
    assert duplicated.status_code == 201
    assert duplicated.json()["id"] == first_id
    assert duplicated.json()["company"] == "Microsoft Corp."

    client.post("/api/watchlist", json={"symbol": "aapl"})
    time.sleep(0.02)  # ensure created_at ordering is stable at second granularity
    client.post("/api/watchlist", json={"symbol": "WLTEST2"})

    listed = client.get("/api/watchlist")
    assert listed.status_code == 200
    items = {item["symbol"]: item for item in listed.json()}
    assert {"MSFT", "AAPL", "WLTEST2"} <= set(items)
    assert items["AAPL"]["company"] is None
    # Most recently added first.
    assert listed.json()[0]["symbol"] == "WLTEST2"

    with SessionLocal() as db:
        count = len(
            db.scalars(
                select(WatchItem).where(WatchItem.symbol == "MSFT")
            ).all()
        )
        assert count == 1

    deleted = client.delete("/api/watchlist/msft")
    assert deleted.status_code == 204
    remaining = {item["symbol"] for item in client.get("/api/watchlist").json()}
    assert "MSFT" not in remaining

    missing = client.delete("/api/watchlist/MSFT")
    assert missing.status_code == 404

    invalid = client.post("/api/watchlist", json={"symbol": "bad symbol!"})
    assert invalid.status_code == 422

    _cleanup(symbols)


def test_watchlist_is_isolated_per_tenant(monkeypatch):
    init_db()
    seed()
    secret = "watchlist-test-secret-with-at-least-32-characters"
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=secret, app_env="local"),
    )
    suffix = uuid4().hex[:8]
    tenant_a = f"watch-a-{suffix}"
    tenant_b = f"watch-b-{suffix}"
    client = csrf_client(main.app)

    try:
        unauthorized = client.get("/api/watchlist")
        assert unauthorized.status_code == 401

        created_a = signed_request(
            client, secret, tenant_a, f"user-a-{suffix}", "POST", "/api/watchlist",
            json_body={"symbol": "TENA"},
        )
        created_b = signed_request(
            client, secret, tenant_b, f"user-b-{suffix}", "POST", "/api/watchlist",
            json_body={"symbol": "TENB"},
        )
        assert created_a.status_code == 201
        assert created_b.status_code == 201

        list_a = signed_request(
            client, secret, tenant_a, f"user-a-{suffix}", "GET", "/api/watchlist"
        ).json()
        list_b = signed_request(
            client, secret, tenant_b, f"user-b-{suffix}", "GET", "/api/watchlist"
        ).json()
        assert {item["symbol"] for item in list_a} == {"TENA"}
        assert {item["symbol"] for item in list_b} == {"TENB"}

        cross_delete = signed_request(
            client, secret, tenant_b, f"user-b-{suffix}", "DELETE", "/api/watchlist/TENA"
        )
        assert cross_delete.status_code == 404

        own_delete = signed_request(
            client, secret, tenant_a, f"user-a-{suffix}", "DELETE", "/api/watchlist/TENA"
        )
        assert own_delete.status_code == 204
    finally:
        _cleanup(["TENA", "TENB"], [tenant_a, tenant_b])

def test_watchlist_concurrent_add_returns_existing_row_not_500(monkeypatch):
    """Doble clic / dos pestañas: la otra petición inserta el mismo símbolo
    entre nuestra lectura y el commit. Antes: IntegrityError -> 500."""
    from app.api.routes import watchlist as watchlist_routes

    init_db()
    seed()
    secret = "watchlist-test-secret-with-at-least-32-characters"
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=secret, app_env="local"),
    )
    suffix = uuid4().hex[:8]
    tenant, user = f"watch-race-{suffix}", f"user-race-{suffix}"
    client = csrf_client(main.app)

    def post(body):
        return signed_request(client, secret, tenant, user, "POST", "/api/watchlist", json_body=body)

    try:
        first = post({"symbol": "WLRACE", "company": "Race Co"})
        assert first.status_code == 201
        first_id = first.json()["id"]

        real_find = watchlist_routes._find_watch_item
        calls = {"n": 0}

        def stale_first_read(db, symbol):
            calls["n"] += 1
            # La primera lectura no ve la fila que «otra pestaña» ya creó.
            return None if calls["n"] == 1 else real_find(db, symbol)

        monkeypatch.setattr(watchlist_routes, "_find_watch_item", stale_first_read)
        raced = post({"symbol": "wlrace", "company": "Race Co SA"})
        assert raced.status_code == 201
        assert raced.json()["id"] == first_id
        assert raced.json()["company"] == "Race Co SA"
        assert calls["n"] == 2

        listed = signed_request(client, secret, tenant, user, "GET", "/api/watchlist").json()
        assert [item["symbol"] for item in listed] == ["WLRACE"]
    finally:
        _cleanup(["WLRACE"], [tenant])


def test_watchlist_same_instant_adds_have_stable_order():
    """Altas con el mismo created_at: desempate por id (más reciente primero)."""
    from datetime import UTC, datetime

    init_db()
    symbols = ["WLTIE1", "WLTIE2", "WLTIE3"]
    _cleanup(symbols)
    client = csrf_client(main.app)
    try:
        for sym in symbols:
            assert client.post("/api/watchlist", json={"symbol": sym}).status_code == 201
        stamp = datetime(2020, 1, 1, tzinfo=UTC)
        with SessionLocal() as db:
            for row in db.scalars(select(WatchItem).where(WatchItem.symbol.in_(symbols))):
                row.created_at = stamp
            db.commit()
        for _ in range(3):
            listed = [i["symbol"] for i in client.get("/api/watchlist").json() if i["symbol"] in symbols]
            assert listed == ["WLTIE3", "WLTIE2", "WLTIE1"]
    finally:
        _cleanup(symbols)


def test_watchlist_delete_missing_is_spanish_404():
    init_db()
    _cleanup(["WLNONE"])
    missing = csrf_client(main.app).delete("/api/watchlist/WLNONE")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Ese ticker no está en tu watchlist"
