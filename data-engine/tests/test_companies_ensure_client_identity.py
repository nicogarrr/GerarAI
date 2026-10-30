"""POST /api/companies/ensure no deja que un usuario fije la identidad global.

`companies` no tiene tenant: nombre, bolsa y sobre todo divisa de la ficha los
comparten todos los usuarios (las posiciones se valoran en esa divisa). Antes el
primer usuario que aseguraba un ticker nuevo podia mandar currency/exchange/name
y quedaban para todos; el enriquecimiento solo rellena placeholders y nunca
corrige una divisa ya puesta.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.api.routes import companies as companies_routes
from app.core.database import SessionLocal, init_db
from app.models import Company
from app.services.company_enrichment_service import CompanyEnrichmentService

TICKER = "ZZQAIDENT"


@pytest.fixture(autouse=True)
def _schema_and_clean():
    init_db()
    _clean()
    yield
    _clean()


def _clean() -> None:
    db = SessionLocal()
    try:
        db.query(Company).filter(Company.ticker == TICKER).delete()
        db.commit()
    finally:
        db.close()


def _stored() -> Company:
    db = SessionLocal()
    try:
        return db.scalar(select(Company).where(Company.ticker == TICKER))
    finally:
        db.close()


POISON = {
    "ticker": TICKER,
    "name": "Nombre inventado",
    "exchange": "LSE",
    "currency": "GBX",
    "sector": "Inventado",
    "industry": "Inventada",
    "domicile_country": "Narnia",
}


def test_production_ignores_client_identity_on_create(monkeypatch):
    monkeypatch.setattr(companies_routes, "_trust_client_identity", lambda: False)
    monkeypatch.setattr(CompanyEnrichmentService, "_finnhub_profile", lambda self, ticker: None)
    response = TestClient(main.app).post("/api/companies/ensure", json=POISON)
    assert response.status_code in (200, 201)
    company = _stored()
    assert company.name == TICKER
    assert company.exchange == "UNKNOWN"
    assert company.currency == "USD"
    assert company.sector == "Unknown"
    assert company.industry == "Unknown"
    assert company.domicile_country is None


@pytest.mark.parametrize("currency", ["DKK", "EUR", "GBP", "GBX"])
def test_production_provider_identity_wins_over_client(monkeypatch, currency):
    monkeypatch.setattr(companies_routes, "_trust_client_identity", lambda: False)
    monkeypatch.setattr(
        CompanyEnrichmentService,
        "_finnhub_profile",
        lambda self, ticker: {"name": "QA Real Corp", "exchange": "NASDAQ NMS - GLOBAL MARKET", "finnhubIndustry": "Technology", "currency": currency},
    )
    response = TestClient(main.app).post("/api/companies/ensure", json=POISON)
    assert response.status_code in (200, 201)
    company = _stored()
    assert company.name == "QA Real Corp"
    assert company.exchange == "NASDAQ NMS - GLOBAL MARKET"
    assert company.currency == currency


def test_production_ignores_client_identity_on_existing_stub(monkeypatch):
    monkeypatch.setattr(CompanyEnrichmentService, "_finnhub_profile", lambda self, ticker: None)
    client = TestClient(main.app)
    assert client.post("/api/companies/ensure", json={"ticker": TICKER}).status_code in (200, 201)
    monkeypatch.setattr(companies_routes, "_trust_client_identity", lambda: False)
    assert client.post("/api/companies/ensure", json=POISON).status_code in (200, 201)
    company = _stored()
    assert company.name == TICKER
    assert company.exchange == "UNKNOWN"
    assert company.sector == "Unknown"
    assert company.domicile_country is None


def test_trust_follows_production_flag(monkeypatch):
    class _Settings:
        is_production = True

    monkeypatch.setattr(companies_routes, "get_settings", lambda: _Settings())
    assert companies_routes._trust_client_identity() is False
    _Settings.is_production = False
    assert companies_routes._trust_client_identity() is True


def test_local_seeding_still_accepts_identity(monkeypatch):
    monkeypatch.setattr(CompanyEnrichmentService, "_finnhub_profile", lambda self, ticker: None)
    response = TestClient(main.app).post("/api/companies/ensure", json=POISON)
    assert response.status_code in (200, 201)
    assert _stored().currency == "GBX"
