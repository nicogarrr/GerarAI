"""Una empresa nueva toma la divisa del proveedor, no USD por defecto (#3113, #3128).

/companies/ensure creaba la ficha con currency="USD" y el enriquecimiento solo
rellena una divisa vacía: una DKK/EUR/GBX nueva quedaba en USD para siempre y
sus importes se valoraban mal. Ahora se crea vacía, el proveedor la rellena y,
si no la da, se usa la del sufijo del ticker (``.CO`` -> DKK) o USD.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.api.routes import companies as companies_routes
from app.core.database import SessionLocal, init_db
from app.models import Company
from app.services.company_enrichment_service import CompanyEnrichmentService, ensure_company_stub

TICKERS = ("ZZQACUR.CO", "ZZQACUR")


@pytest.fixture(autouse=True)
def _schema_and_clean():
    init_db()
    _clean()
    yield
    _clean()


def _clean() -> None:
    db = SessionLocal()
    try:
        db.query(Company).filter(Company.ticker.in_(TICKERS)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _currency(ticker: str) -> str:
    db = SessionLocal()
    try:
        return db.scalar(select(Company.currency).where(Company.ticker == ticker))
    finally:
        db.close()


def _profile(currency):
    def fake(self, ticker):
        return {"name": "QA Corp", "exchange": "OMX Copenhagen", "finnhubIndustry": "Banking", "currency": currency}

    return fake


@pytest.mark.parametrize("trusted", [True, False])
def test_new_dkk_company_ends_up_dkk_after_enrichment(monkeypatch, trusted):
    monkeypatch.setattr(companies_routes, "_trust_client_identity", lambda: trusted)
    monkeypatch.setattr(CompanyEnrichmentService, "_finnhub_profile", _profile("DKK"))
    response = TestClient(main.app).post("/api/companies/ensure", json={"ticker": "ZZQACUR.CO"})
    assert response.status_code in (200, 201)
    assert _currency("ZZQACUR.CO") == "DKK"


@pytest.mark.parametrize("trusted", [True, False])
def test_provider_without_currency_falls_back_to_ticker_suffix(monkeypatch, trusted):
    monkeypatch.setattr(companies_routes, "_trust_client_identity", lambda: trusted)
    monkeypatch.setattr(CompanyEnrichmentService, "_finnhub_profile", lambda self, ticker: None)
    client = TestClient(main.app)
    assert client.post("/api/companies/ensure", json={"ticker": "ZZQACUR.CO"}).status_code in (200, 201)
    assert client.post("/api/companies/ensure", json={"ticker": "ZZQACUR"}).status_code in (200, 201)
    assert _currency("ZZQACUR.CO") == "DKK"
    assert _currency("ZZQACUR") == "USD"


def test_trusted_client_currency_still_wins(monkeypatch):
    monkeypatch.setattr(companies_routes, "_trust_client_identity", lambda: True)
    monkeypatch.setattr(CompanyEnrichmentService, "_finnhub_profile", _profile("DKK"))
    response = TestClient(main.app).post("/api/companies/ensure", json={"ticker": "ZZQACUR.CO", "currency": "eur"})
    assert response.status_code in (200, 201)
    assert _currency("ZZQACUR.CO") == "EUR"


@pytest.mark.parametrize("provider, expected", [("DKK", "DKK"), (None, "DKK")])
def test_ensure_company_stub_takes_provider_or_suffix_currency(monkeypatch, provider, expected):
    monkeypatch.setattr(
        CompanyEnrichmentService,
        "_finnhub_profile",
        _profile(provider) if provider else (lambda self, ticker: None),
    )
    db = SessionLocal()
    try:
        ensure_company_stub(db, "zzqacur.co")
    finally:
        db.close()
    assert _currency("ZZQACUR.CO") == expected
