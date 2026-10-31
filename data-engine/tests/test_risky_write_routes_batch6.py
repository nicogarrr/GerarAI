"""Rutas de escritura de riesgo sin test directo (lote 6, ultimo).

- POST /api/companies/{ticker}/kpi-registry/sync: ticker desconocido -> 404
  fijo; servicio con doble -> 200 con la lista serializada.
- POST /api/companies/{ticker}/moat/refresh: ticker desconocido -> 404;
  servicio con doble -> 200 con el payload.
- POST /api/sources/documents/index/rebuild: doble del indice -> 200;
  ValueError del indice -> 400 (nunca 500 opaco).
- POST /api/portfolio/refresh-market: ValueError del servicio -> 400 con el
  detalle; doble async -> 200 con el resumen.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "risky-write-routes-b6-test-secret-at-least-32-chars"


def _setup(monkeypatch, *, with_company: bool = False):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"risky-b6-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Risky b6"))
    if with_company and not db.query(Company).filter_by(ticker="B6TEST").first():
        db.add(
            Company(
                ticker="B6TEST",
                name="B6 Test Co",
                currency="USD",
                exchange="NASDAQ",
                sector="Tech",
                industry="Test",
                company_type="standard",
                valuation_model="standard_dcf",
            )
        )
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext


def test_kpi_registry_sync_unknown_ticker_404(monkeypatch):
    client, tenant = _setup(monkeypatch)
    res = signed_request(
        client, SECRET, tenant, "u1", "POST",
        "/api/companies/ZZZNOPE/kpi-registry/sync",
    )
    assert res.status_code == 404, res.text
    assert res.json()["detail"] == "Company not found"


def test_kpi_registry_sync_runs_service(monkeypatch):
    import app.api.routes.companies as companies_routes

    class _FakeService:
        def sync(self, db, company):
            return []

    monkeypatch.setattr(companies_routes, "CompanyKPIRegistryService", _FakeService)
    client, tenant = _setup(monkeypatch, with_company=True)
    res = signed_request(
        client, SECRET, tenant, "u1", "POST",
        "/api/companies/B6TEST/kpi-registry/sync",
    )
    assert res.status_code == 200, res.text
    assert res.json() == []


def test_moat_refresh_unknown_ticker_404(monkeypatch):
    client, tenant = _setup(monkeypatch)
    res = signed_request(
        client, SECRET, tenant, "u1", "POST",
        "/api/companies/ZZZNOPE/moat/refresh",
    )
    assert res.status_code == 404, res.text
    assert res.json()["detail"] == "Company not found"


def test_moat_refresh_runs_service(monkeypatch):
    import app.api.routes.companies as companies_routes

    class _FakeService:
        def assess(self, db, company, persist=False):
            assert persist is True
            return {"ticker": company.ticker, "moat_score": 0.5}

    monkeypatch.setattr(companies_routes, "MoatService", _FakeService)
    client, tenant = _setup(monkeypatch, with_company=True)
    res = signed_request(
        client, SECRET, tenant, "u1", "POST",
        "/api/companies/B6TEST/moat/refresh",
    )
    assert res.status_code == 200, res.text
    assert res.json()["ticker"] == "B6TEST"


def test_sources_rebuild_returns_summary(monkeypatch):
    import app.api.routes.sources as sources_routes

    class _FakeIndex:
        def rebuild_tenant(self, db):
            return {"indexed": 3, "skipped": 1}

    monkeypatch.setattr(sources_routes, "RAGIndex", _FakeIndex)
    client, tenant = _setup(monkeypatch)
    res = signed_request(
        client, SECRET, tenant, "u1", "POST",
        "/api/sources/documents/index/rebuild",
    )
    assert res.status_code == 200, res.text
    assert res.json()["indexed"] == 3


def test_sources_rebuild_value_error_is_400(monkeypatch):
    import app.api.routes.sources as sources_routes

    class _BadIndex:
        def rebuild_tenant(self, db):
            raise ValueError("indice corrupto")

    monkeypatch.setattr(sources_routes, "RAGIndex", _BadIndex)
    client, tenant = _setup(monkeypatch)
    res = signed_request(
        client, SECRET, tenant, "u1", "POST",
        "/api/sources/documents/index/rebuild",
    )
    assert res.status_code == 400, res.text
    assert "indice corrupto" in res.text


def test_refresh_market_value_error_is_400(monkeypatch):
    import app.api.routes.portfolio as portfolio_routes

    class _BadService:
        def refresh(self, db, as_of=None):
            raise ValueError("as_of fuera de rango")

    monkeypatch.setattr(portfolio_routes, "MarketRefreshService", _BadService)
    client, tenant = _setup(monkeypatch)
    res = signed_request(
        client, SECRET, tenant, "u1", "POST", "/api/portfolio/refresh-market",
    )
    assert res.status_code == 400, res.text
    assert "as_of fuera de rango" in res.text


def test_refresh_market_runs_service(monkeypatch):
    import app.api.routes.portfolio as portfolio_routes

    class _FakeService:
        async def refresh(self, db, as_of=None):
            return {"refreshed": 5, "as_of": str(as_of) if as_of else None}

    monkeypatch.setattr(portfolio_routes, "MarketRefreshService", _FakeService)
    client, tenant = _setup(monkeypatch)
    res = signed_request(
        client, SECRET, tenant, "u1", "POST", "/api/portfolio/refresh-market",
    )
    assert res.status_code == 200, res.text
    assert res.json()["refreshed"] == 5
