"""POST /api/companies/verify-identity: doble coincidencia SEC + proveedor."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core.database import SessionLocal, init_db
from app.models import Company
from app.services.connectors.finnhub import FinnhubClient
from app.services.connectors.sec import SECClient

TICKER = "ZZQAVID"

SEC_ENTRY = {"cik_str": 9999999, "ticker": TICKER, "title": "QA Verify Corp"}
PROVIDER_PROFILE = {
    "ticker": TICKER,
    "name": "QA Verify Corp",
    "exchange": "NASDAQ NMS - GLOBAL MARKET",
    "country": "US",
    "currency": "USD",
}


@pytest.fixture(autouse=True)
def _schema():
    init_db()


def _clean() -> None:
    db = SessionLocal()
    try:
        db.query(Company).filter(Company.ticker == TICKER).delete()
        db.commit()
    finally:
        db.close()


def _mock_sources(monkeypatch, sec_entry, provider_profile):
    async def ticker_map(self):
        return {"0": sec_entry} if sec_entry is not None else {}

    async def profile(self, ticker):
        return provider_profile

    monkeypatch.setattr(SECClient, "ticker_map", ticker_map)
    monkeypatch.setattr(FinnhubClient, "configured", lambda self: True)
    monkeypatch.setattr(FinnhubClient, "profile", profile)


def test_verified_double_match_creates_labeled_stub(monkeypatch):
    _clean()
    _mock_sources(monkeypatch, SEC_ENTRY, PROVIDER_PROFILE)
    response = TestClient(main.app).post("/api/companies/verify-identity", json={"ticker": TICKER})
    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is True
    assert payload["company"]["ticker"] == TICKER
    assert payload["company"]["name"] == "QA Verify Corp"
    assert payload["company"]["cik"] == "0009999999"
    assert payload["company"]["exchange"] == "NASDAQ NMS - GLOBAL MARKET"
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == TICKER))
        assert company is not None
        assert "identity:sec+finnhub" in company.special_sources
        assert company.company_type == "research_candidate"
    finally:
        db.close()
    _clean()


def test_negative_no_sec_record_creates_nothing(monkeypatch):
    _clean()
    _mock_sources(monkeypatch, None, PROVIDER_PROFILE)
    response = TestClient(main.app).post("/api/companies/verify-identity", json={"ticker": TICKER})
    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is False
    assert payload["company"] is None
    assert any(r.startswith("sec_sin_registro") for r in payload["reasons"])
    db = SessionLocal()
    try:
        assert db.scalar(select(Company).where(Company.ticker == TICKER)) is None
    finally:
        db.close()


def test_negative_name_mismatch_creates_nothing(monkeypatch):
    _clean()
    _mock_sources(monkeypatch, SEC_ENTRY, {**PROVIDER_PROFILE, "name": "Almonty Industries Inc"})
    payload = TestClient(main.app).post("/api/companies/verify-identity", json={"ticker": TICKER}).json()
    assert payload["verified"] is False
    assert any(r.startswith("nombre_no_coincide") for r in payload["reasons"])
    db = SessionLocal()
    try:
        assert db.scalar(select(Company).where(Company.ticker == TICKER)) is None
    finally:
        db.close()


def test_negative_non_us_exchange_creates_nothing(monkeypatch):
    _clean()
    _mock_sources(monkeypatch, SEC_ENTRY, {**PROVIDER_PROFILE, "exchange": "BOLSA MEXICANA DE VALORES"})
    payload = TestClient(main.app).post("/api/companies/verify-identity", json={"ticker": TICKER}).json()
    assert payload["verified"] is False
    assert any(r.startswith("mercado_no_sec") for r in payload["reasons"])


def test_existing_master_company_short_circuits(monkeypatch):
    _clean()
    db = SessionLocal()
    try:
        db.add(Company(ticker=TICKER, name="Master Corp", exchange="NASDAQ",
                       company_type="research_candidate", valuation_model="unassigned"))
        db.commit()
    finally:
        db.close()
    # Sin mocks de red: no debe llamar a ninguna fuente si ya está en el maestro.
    payload = TestClient(main.app).post("/api/companies/verify-identity", json={"ticker": TICKER}).json()
    assert payload["verified"] is True
    assert payload["already_in_master"] is True
    assert payload["company"]["name"] == "Master Corp"
    _clean()


def test_get_identity_verification_is_read_only(monkeypatch):
    """El render GET comprueba la identidad pero NUNCA crea la ficha."""
    _clean()
    _mock_sources(monkeypatch, SEC_ENTRY, PROVIDER_PROFILE)
    response = TestClient(main.app).get("/api/companies/identity-verification", params={"ticker": TICKER})
    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is True
    assert payload["company"] is None
    db = SessionLocal()
    try:
        assert db.scalar(select(Company).where(Company.ticker == TICKER)) is None
    finally:
        db.close()


def test_negative_homonym_in_master_rejects(monkeypatch):
    """Homónimo con otra identidad en el maestro: la doble coincidencia US no basta."""
    _clean()
    db = SessionLocal()
    try:
        db.add(Company(ticker=f"{TICKER}.MC", name="Almirall SA", exchange="BME",
                       company_type="research_candidate", valuation_model="unassigned"))
        db.commit()
    finally:
        db.close()
    _mock_sources(monkeypatch, SEC_ENTRY, PROVIDER_PROFILE)
    response = TestClient(main.app).post("/api/companies/verify-identity", json={"ticker": TICKER})
    payload = response.json()
    assert payload["verified"] is False
    assert any(r.startswith("ticker_ambiguo") for r in payload["reasons"])
    db = SessionLocal()
    try:
        assert db.scalar(select(Company).where(Company.ticker == TICKER)) is None
        homonym = db.scalar(select(Company).where(Company.ticker == f"{TICKER}.MC"))
        assert homonym is not None and homonym.name == "Almirall SA"
        db.delete(homonym)
        db.commit()
    finally:
        db.close()


def test_negative_missing_currency_creates_nothing(monkeypatch):
    _clean()
    _mock_sources(monkeypatch, SEC_ENTRY, {**PROVIDER_PROFILE, "currency": ""})
    payload = TestClient(main.app).post("/api/companies/verify-identity", json={"ticker": TICKER}).json()
    assert payload["verified"] is False
    assert any(r.startswith("moneda_desconocida") for r in payload["reasons"])
    db = SessionLocal()
    try:
        assert db.scalar(select(Company).where(Company.ticker == TICKER)) is None
    finally:
        db.close()


def test_double_click_race_returns_existing_company_not_500(monkeypatch):
    """Doble clic en «Abrir ficha»: el segundo POST ya no da 500."""
    from app.api.routes import companies as companies_route

    _clean()
    _mock_sources(monkeypatch, SEC_ENTRY, PROVIDER_PROFILE)
    client = TestClient(main.app, raise_server_exceptions=False)
    first = client.post("/api/companies/verify-identity", json={"ticker": TICKER})
    assert first.status_code == 200 and first.json()["company"]["ticker"] == TICKER

    # Simula la carrera: la 2.ª petición leyó el maestro antes de que la 1.ª
    # confirmara, así que su comprobación inicial no ve la ficha.
    real_resolve = companies_route.resolve_company
    calls = {"n": 0}

    def stale_then_real(db, ticker):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_resolve(db, ticker)

    monkeypatch.setattr(companies_route, "resolve_company", stale_then_real)
    second = client.post("/api/companies/verify-identity", json={"ticker": TICKER})
    assert second.status_code == 200
    payload = second.json()
    assert payload["already_in_master"] is True
    assert payload["company"]["ticker"] == TICKER
    db = SessionLocal()
    try:
        assert db.query(Company).filter(Company.ticker == TICKER).count() == 1
    finally:
        db.close()
    _clean()
