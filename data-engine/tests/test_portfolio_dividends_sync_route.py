"""POST /api/portfolio/dividends/sync con response_model.

Envelope medido contra DividendIngestionService.sync_portfolio (6 claves
siempre presentes); provenance reutiliza ProvenanceOut. Los items de
results varian por rama (medido contra ProviderIngestionService.sync_company
y el override de dividendos) y la ruta usa exclude_unset. El test ejercita
el wire vacio (sin posiciones ni watchlist no hay llamadas al proveedor:
nada que inventar); las variantes de item quedan declaradas desde los
caminos medidos del servicio. Servicio real, sin mock.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant, WatchItem
from app.models.entities import Base
from app.schemas.api import PortfolioDividendSyncOut
from app.services.dividend_ingestion_service import DividendIngestionService
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-dividends-sync-test-secret"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-dividends-sync-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio dividends sync test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-dividends-sync-user"


def test_sync_empty_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "POST", "/api/portfolio/dividends/sync")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioDividendSyncOut.model_validate(payload)
    # Las 6 claves del envelope, ni una mas ni una menos.
    assert set(payload) == {
        "companies",
        "synced",
        "unavailable",
        "currency_unknown",
        "results",
        "provenance",
    }
    # Sin posiciones ni watchlist: nada que sincronizar, cobertura OK.
    assert payload["companies"] == 0
    assert payload["synced"] == 0
    assert payload["unavailable"] == 0
    assert payload["currency_unknown"] == 0
    assert payload["results"] == []
    provenance = payload["provenance"]
    assert provenance["coverage"] == "ok"
    assert provenance["source_kind"] == "unofficial"
    assert provenance["source"].startswith("Yahoo Finance")
    assert "note" in provenance  # _PROVENANCE_NOTE siempre se emite aqui
    assert provenance["fetched_at"]


def _seed_watch_item(tenant_ext: str, symbol: str) -> None:
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant_ext).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(WatchItem(symbol=symbol))
    db.commit()
    db.close()


def test_sync_no_safe_symbol_variant_wire(monkeypatch) -> None:
    """Variante no_safe_symbol por HTTP real, sin red: la bolsa TEST no tiene
    simbolo Yahoo seguro (yahoo_symbol -> None, medido) y el servicio corta
    antes de llamar al proveedor."""
    client, tenant, user = _client(monkeypatch)
    ticker = f"NOSAFE{uuid4().hex[:4].upper()}"[:20]
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(Company(
        ticker=ticker, name="No safe symbol test co", exchange="TEST",
        currency="EUR", company_type="stock", valuation_model="dcf",
    ))
    db.commit()
    db.close()
    _seed_watch_item(tenant, ticker)

    res = signed_request(client, SECRET, tenant, user, "POST", "/api/portfolio/dividends/sync")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioDividendSyncOut.model_validate(payload)
    assert payload["companies"] == 1
    assert payload["synced"] == 0
    # Medido en sync_portfolio: no_safe_symbol no cuenta como unavailable.
    assert payload["unavailable"] == 0
    assert payload["currency_unknown"] == 0
    item = payload["results"][0]
    # Las 5 claves de la variante, ni una mas (exclude_unset en la ruta).
    assert set(item) == {"ticker", "status", "error", "inserted", "existing"}
    assert item["ticker"] == ticker
    assert item["status"] == "no_safe_symbol"
    assert item["error"]
    assert item["inserted"] == 0
    assert item["existing"] == 0


# --- Variantes de proveedor a nivel servicio ----------------------------------
# El proveedor es la frontera de red: se sustituye por un doble en el
# constructor (precedente _NoProvider de test_dividend_currency_mismatch).
# El servicio de ingestion es el real y la serializacion es la misma de la
# ruta: PortfolioDividendSyncOut + exclude_unset.


def _service_db(tenant_ext: str):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id=tenant_ext, name="Dividend sync variants")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return db


def _wire(db) -> dict:
    envelope = asyncio.run(DividendIngestionService(
        fmp=_FmpDouble(), yahoo=_YahooDouble(),
    ).sync_portfolio(db))
    # Misma serializacion que la ruta: response_model + exclude_unset.
    return PortfolioDividendSyncOut.model_validate(envelope).model_dump(
        exclude_unset=True
    )


class _YahooDouble:
    rows: list[dict] = []
    currency: str | None = "USD"
    fail = False

    async def dividend_events(self, symbol: str):
        if type(self).fail:
            raise RuntimeError("yahoo caido (doble)")
        return {"rows": type(self).rows, "currency": type(self).currency}


class _FmpDouble:
    fail = False

    async def dividends(self, symbol: str):
        if type(self).fail:
            raise RuntimeError("fmp caido (doble)")
        return []


def _variant_company(db, ticker: str) -> None:
    db.add(Company(
        ticker=ticker, name="Variant test co", exchange="NYSE",
        currency="USD", company_type="stock", valuation_model="dcf",
    ))
    db.add(WatchItem(symbol=ticker))
    db.commit()


def test_sync_ok_variant_wire() -> None:
    suffix = uuid4().hex[:4].upper()
    db = _service_db(f"dividend-variant-ok-{suffix}")
    ticker = f"OK{suffix}"
    _variant_company(db, ticker)
    _YahooDouble.rows = [{"date": 1761177600, "amount": 0.5}]
    _YahooDouble.currency = "USD"
    _YahooDouble.fail = False
    _FmpDouble.fail = False

    payload = _wire(db)

    assert payload["companies"] == 1
    assert payload["synced"] == 1
    assert payload["unavailable"] == 0
    assert payload["currency_unknown"] == 0
    item = payload["results"][0]
    # Variante ok medida: source/skipped/fetched_at presentes; sin error,
    # reason, currency_unknown_rows ni split_readjustments_healed.
    assert set(item) == {
        "ticker", "status", "source", "inserted", "existing", "skipped",
        "fetched_at",
    }
    assert item["status"] == "ok"
    assert item["source"] == "yahoo_finance"
    assert item["inserted"] == 1
    assert item["existing"] == 0
    db.close()


def test_sync_unavailable_variant_wire() -> None:
    suffix = uuid4().hex[:4].upper()
    db = _service_db(f"dividend-variant-down-{suffix}")
    ticker = f"DOWN{suffix}"
    _variant_company(db, ticker)
    _YahooDouble.fail = True
    _FmpDouble.fail = True

    payload = _wire(db)

    assert payload["synced"] == 0
    assert payload["unavailable"] == 1
    item = payload["results"][0]
    # Variante unavailable medida: error presente; sin source/skipped/fetched_at.
    assert set(item) == {"ticker", "status", "error", "inserted", "existing"}
    assert item["status"] == "unavailable"
    assert item["error"]
    # Cobertura honesta: sin exitos la proveniencia no puede decir ok.
    assert payload["provenance"]["coverage"] == "unavailable"
    _YahooDouble.fail = False
    _FmpDouble.fail = False
    db.close()


def test_sync_currency_unknown_variant_wire() -> None:
    suffix = uuid4().hex[:4].upper()
    db = _service_db(f"dividend-variant-cur-{suffix}")
    ticker = f"CUR{suffix}"
    _variant_company(db, ticker)
    _YahooDouble.rows = [{"date": 1761177600, "amount": 0.5}]
    _YahooDouble.currency = None  # el proveedor no informa la divisa
    _YahooDouble.fail = False
    _FmpDouble.fail = False

    payload = _wire(db)

    assert payload["synced"] == 0
    assert payload["currency_unknown"] == 1
    item = payload["results"][0]
    # Variante currency_unknown medida: + currency_unknown_rows y reason.
    assert set(item) == {
        "ticker", "status", "source", "inserted", "existing", "skipped",
        "fetched_at", "currency_unknown_rows", "reason",
    }
    assert item["status"] == "currency_unknown"
    assert item["currency_unknown_rows"] == 1
    assert item["reason"]
    assert item["skipped"] == {"unknown_currency": 1}
    _YahooDouble.currency = "USD"
    db.close()
