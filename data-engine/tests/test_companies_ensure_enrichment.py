"""POST /api/companies/ensure enriquece stubs via CompanyEnrichmentService.

Los callers (crear alerta, Propicks) mandan solo el ticker; sin enrichment la
ficha quedaba con name=ticker y sector/industry/exchange "Unknown" para
siempre (visto en prod: AAPL "Unknown . Unknown"). El ensure ahora enriquece
best-effort desde Finnhub; si la API no tiene datos, el stub se crea igual.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core.csrf import generate_csrf_token
from app.core.database import SessionLocal, init_db
from app.models import Company
from app.services.company_enrichment_service import CompanyEnrichmentService

TICKER = "ZZQAENSURE"


@pytest.fixture(autouse=True)
def _schema():
    # Mismo patron que test_materiality_service / test_valuation_integrity:
    # las tablas las crea init_db, no el orden de la suite. Con xdist cada
    # worker es un proceso nuevo con su propia sqlite, y este fichero puede
    # caer el primero en su worker sin que ningun TestClient haya arrancado
    # la app (y su lifespan -> init_db) antes en ese proceso.
    init_db()


def _clean() -> None:
    db = SessionLocal()
    try:
        db.query(Company).filter(Company.ticker == TICKER).delete()
        db.commit()
    finally:
        db.close()


def test_ensure_enriches_ticker_only_stub(monkeypatch):
    _clean()
    monkeypatch.setattr(
        CompanyEnrichmentService,
        "_finnhub_profile",
        lambda self, ticker: {
            "name": "QA Ensure Corp",
            "exchange": "NASDAQ NMS - GLOBAL MARKET",
            "finnhubIndustry": "Technology",
            "currency": "USD",
        },
    )
    response = TestClient(main.app, headers={"X-CSRF-Token": generate_csrf_token()}).post("/api/companies/ensure", json={"ticker": TICKER})
    assert response.status_code in (200, 201)
    payload = response.json()
    assert payload["name"] == "QA Ensure Corp"
    assert payload["exchange"] == "NASDAQ NMS - GLOBAL MARKET"
    assert payload["currency"] == "USD"
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == TICKER))
        assert company.name == "QA Ensure Corp"
        assert company.industry == "Technology"
    finally:
        db.close()
    _clean()


def test_ensure_survives_enrichment_failure(monkeypatch):
    """Si la API de mercado no tiene datos, el stub honesto se crea igual."""
    _clean()
    monkeypatch.setattr(
        CompanyEnrichmentService, "_finnhub_profile", lambda self, ticker: None
    )
    response = TestClient(main.app, headers={"X-CSRF-Token": generate_csrf_token()}).post("/api/companies/ensure", json={"ticker": TICKER})
    assert response.status_code in (200, 201)
    payload = response.json()
    assert payload["ticker"] == TICKER
    assert payload["name"] == TICKER  # stub honesto, nunca inventado
    _clean()
