"""Rutas de escritura de riesgo sin test directo (lote 5).

- POST /api/work-products/generate: ticker desconocido -> 404 fijo (sin
  filtrar internos); servicio con doble -> 200 con el payload.
- POST /api/thesis/{ticker}/approve (transicion de estado de tesis):
  ticker desconocido -> 404; sin tesis persistida -> 404 honesto (nunca
  aprueba algo que no existe).
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "risky-write-routes-b5-test-secret-at-least-32-chars"


def _setup(monkeypatch, *, with_company: bool = False):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"risky-b5-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Risky b5"))
    if with_company and not db.query(Company).filter_by(ticker="WPTEST").first():
        db.add(
            Company(
                ticker="WPTEST",
                name="WP Test Co",
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


def test_work_products_generate_unknown_ticker_404(monkeypatch):
    client, tenant = _setup(monkeypatch)
    res = signed_request(
        client, SECRET, tenant, "u1", "POST", "/api/work-products/generate",
        json_body={"product_type": "one_page_memo", "ticker": "ZZZNOPE", "years": 1},
    )
    assert res.status_code == 404, res.text
    assert res.json()["detail"] == "Company not found"


def test_work_products_generate_runs_service(monkeypatch):
    import app.api.routes.work_products as wp_routes

    class _FakeService:
        def generate(self, db, *, product_type, company, years):
            return {"status": "ok", "product_type": product_type, "ticker": company.ticker}

    monkeypatch.setattr(wp_routes, "WorkProductService", _FakeService)
    client, tenant = _setup(monkeypatch, with_company=True)
    res = signed_request(
        client, SECRET, tenant, "u1", "POST", "/api/work-products/generate",
        json_body={"product_type": "one_page_memo", "ticker": "WPTEST", "years": 1},
    )
    assert res.status_code == 200, res.text
    assert res.json()["ticker"] == "WPTEST"


def test_thesis_approve_unknown_ticker_404(monkeypatch):
    client, tenant = _setup(monkeypatch)
    res = signed_request(
        client, SECRET, tenant, "u1", "POST", "/api/thesis/ZZZNOPE/approve",
        json_body={"decision": "approved"},
    )
    assert res.status_code == 404, res.text


def test_thesis_approve_without_persisted_thesis_404(monkeypatch):
    """Nunca aprueba una tesis que no existe: 404 honesto."""
    client, tenant = _setup(monkeypatch, with_company=True)
    res = signed_request(
        client, SECRET, tenant, "u1", "POST", "/api/thesis/WPTEST/approve",
        json_body={"decision": "approved"},
    )
    assert res.status_code == 404, res.text
    assert "No thesis" in res.text
