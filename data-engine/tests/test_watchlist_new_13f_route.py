"""GET /api/watchlist/new-13f: nuevas posiciones institucionales (13F) por
empresa de la watchlist del tenant firmado.

Agregación compacta sobre institutional_holders (lectura de datos guardados,
sin red): un item por watch item del tenant; sin snapshot -> status sin_datos
con motivo, nunca una lista inventada.

La empresa del fixture es SINTÉTICA (ticker ZZ13FWL, ISIN US13FWATCH04 ->
CUSIP 13FWATCH0): la base de datos de la suite es compartida y un ticker real
como AAPL puede existir ya creado por otro test SIN identificadores, y entonces
la lectura es sin_identificador por contrato (fail-closed de identidad), no por
un bug de la ruta. Convención del repo: tickers sintéticos en tests.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant, WatchItem
from app.services import institutional_holders as ih
from app.services.connectors import form13f_dataset as ds
from tests.auth_helpers import auth_settings, signed_request
from tests.test_institutional_holders import OTHER, _info, _zip

SECRET = "watchlist-new13f-secret-"
TICKER = "ZZ13FWL"
ISIN = "US13FWATCH04"
CUSIP = "13FWATCH0"


def _parsed_pair():
    """Mismo caso que tests.test_institutional_new_positions.parsed_pair pero
    para el CUSIP sintético: 14 gestores con 13F previo sin este valor (nuevas
    de verdad) y un 15.º sin 13F previo (no cuenta como nueva)."""
    prev = _zip([f"P{i}\t15-MAY-2026\t13F-HR\t{i}\t31-MAR-2026" for i in range(1, 15)], [],
                [_info(f"P{i}", OTHER, 1) for i in range(1, 15)])
    subs = [f"C{i}\t15-AUG-2026\t13F-HR\t{i}\t30-JUN-2026" for i in range(1, 16)]
    infos = [_info(f"C{i}", CUSIP, i).replace("\t1\t" + str(i) + "\tSH", "\t" + str(1000 - i * 10) + "\t" + str(i) + "\tSH")
             for i in range(1, 16)]
    now = _zip(subs, [], infos)
    return [ds.parse_dataset(now, {CUSIP}, url="https://www.sec.gov/current.zip"),
            ds.parse_dataset(prev, {CUSIP}, url="https://www.sec.gov/prior.zip")]


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


def _ingest_synthetic() -> None:
    db = SessionLocal()
    if db.query(Company).filter(Company.ticker == TICKER).first() is None:
        db.add(
            Company(
                ticker=TICKER,
                name="Sintética 13F",
                exchange="NASDAQ",
                company_type="mature",
                valuation_model="dcf",
                isin=ISIN,
            )
        )
        db.commit()
    # Idempotente por checksum (tests.test_institutional_holders).
    ih.ingest_parsed(db, _parsed_pair(), ["new13f-route", "old13f-route"], ih.universe_cusips(db))
    db.close()


def test_new_13f_items_per_watchlist_ticker(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    _ingest_synthetic()
    _seed(tenant, [TICKER, "ZZSINTRECEF"])

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist/new-13f")
    assert res.status_code == 200, res.text
    items = {item["ticker"]: item for item in res.json()["items"]}
    assert set(items) == {TICKER, "ZZSINTRECEF"}

    row = items[TICKER]
    assert row["status"] == "ok"
    assert row["period"] == "2026-06-30"
    np = row["new_positions"]
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
    _ingest_synthetic()
    _seed(tenant, [TICKER])
    other_ext = f"watchlist-new13f-otro-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=other_ext, name="Otro tenant"))
    db.commit()
    db.close()
    _seed(other_ext, ["ZZOTRO"])

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist/new-13f")
    assert res.status_code == 200, res.text
    tickers = [item["ticker"] for item in res.json()["items"]]
    assert tickers == [TICKER]
