"""Rotulo de causa real: un FPI (emisor extranjero) no presenta Form 4."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import insider as insider_module
from app.core.database import get_db
from app.models.entities import Base, Company, Tenant


def _client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(engine)()
    db.add(Tenant(id=1, external_id="t"))
    db.add_all([
        Company(id=1, ticker="BN", name="Brookfield", exchange="NYSE",
                company_type="large_cap", valuation_model="dcf", domicile_country="Canada"),
        Company(id=2, ticker="AAPL", name="Apple", exchange="NASDAQ",
                company_type="large_cap", valuation_model="dcf", domicile_country="United States"),
        Company(id=3, ticker="CGEO.L", name="CGEO", exchange="LSE",
                company_type="small_cap", valuation_model="dcf", domicile_country="Georgia"),
        Company(id=4, ticker="SINPAIS", name="SinPais", exchange="NYSE",
                company_type="large_cap", valuation_model="dcf"),
    ])
    db.commit()
    app = FastAPI()
    app.include_router(insider_module.router, prefix="/api/insider")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_foreign_issuer_label():
    client = _client()
    assert client.get("/api/insider/filings", params={"ticker": "BN"}).json()["foreign_issuer"] is True
    assert client.get("/api/insider/filings", params={"ticker": "CGEO.L"}).json()["foreign_issuer"] is True
    assert client.get("/api/insider/filings", params={"ticker": "AAPL"}).json()["foreign_issuer"] is False
    # Sin domicilio curado o sin ficha: se desconoce la causa, nunca se afirma.
    assert client.get("/api/insider/filings", params={"ticker": "SINPAIS"}).json()["foreign_issuer"] is None
    assert client.get("/api/insider/filings", params={"ticker": "NOEXISTE"}).json()["foreign_issuer"] is None
