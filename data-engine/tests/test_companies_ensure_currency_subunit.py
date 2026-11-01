"""POST /api/companies/ensure (solo local/test) conserva la subunidad de la divisa.

En no-produccion la ruta acepta la divisa del cliente para sembrar datos, pero
la pasaba por ``.upper()``: ``GBp`` (peniques) se guardaba como ``GBP``
(libras) y la ficha valoraba la posicion 100 veces mas cara. Un texto que no
es divisa («NaN», «XYZ») se guardaba tal cual; ahora cae a la divisa por
defecto del listado, como si no se hubiera mandado.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.api.routes import companies as companies_routes
from app.core.csrf import generate_csrf_token
from app.core.database import SessionLocal, init_db
from app.models import Company
from app.services.company_enrichment_service import CompanyEnrichmentService

TICKER = "ZZQASUBU.L"


@pytest.fixture(autouse=True)
def _schema_and_clean(monkeypatch):
    init_db()
    _clean()
    monkeypatch.setattr(companies_routes, "_trust_client_identity", lambda: True)
    monkeypatch.setattr(CompanyEnrichmentService, "_finnhub_profile", lambda self, ticker: None)
    yield
    _clean()


def _clean() -> None:
    db = SessionLocal()
    try:
        db.query(Company).filter(Company.ticker == TICKER).delete()
        db.commit()
    finally:
        db.close()


def _ensure(currency: str) -> str:
    client = TestClient(main.app, headers={"X-CSRF-Token": generate_csrf_token()})
    response = client.post("/api/companies/ensure", json={"ticker": TICKER, "currency": currency})
    assert response.status_code in (200, 201), response.text
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == TICKER))
        assert company is not None
        return company.currency
    finally:
        db.close()


@pytest.mark.parametrize(
    ("sent", "stored"),
    [("GBp", "GBp"), ("ZAc", "ZAc"), ("GBX", "GBX"), ("gbp", "GBP"), (" eur ", "EUR")],
)
def test_subunidad_del_cliente_se_conserva(sent, stored):
    assert _ensure(sent) == stored


@pytest.mark.parametrize("sent", ["NaN", "XYZ", "EURO"])
def test_divisa_inventada_cae_a_la_del_listado(sent):
    # .L cotiza en peniques: misma reserva que sin divisa.
    assert _ensure(sent) == "GBX"
