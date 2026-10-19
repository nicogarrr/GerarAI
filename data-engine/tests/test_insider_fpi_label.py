"""Rotulo de causa real: un FPI (emisor extranjero) no presenta Form 4.

El estatus FPI se deriva de los formularios SEC guardados (20-F/40-F/6-K sin
10-K/10-Q), NUNCA del domicilio: Chubb, Accenture o Schlumberger domicilian
fuera de EE. UU. y presentan 10-K (objecion del auditor, 20/10/2026).
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import insider as insider_module
from app.core.database import get_db
from app.models.entities import Base, Company, Document, Tenant


def _client():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(engine)()
    db.add(Tenant(id=1, external_id="t"))
    companies = [
        Company(
            id=1,
            ticker="BN",
            name="Brookfield",
            exchange="NYSE",
            company_type="large_cap",
            valuation_model="dcf",
            domicile_country="Canada",
        ),
        Company(
            id=2,
            ticker="AAPL",
            name="Apple",
            exchange="NASDAQ",
            company_type="large_cap",
            valuation_model="dcf",
            domicile_country="United States",
        ),
        Company(
            id=3,
            ticker="CGEO.L",
            name="CGEO",
            exchange="LSE",
            company_type="small_cap",
            valuation_model="dcf",
            domicile_country="Georgia",
        ),
        Company(
            id=4,
            ticker="CB",
            name="Chubb",
            exchange="NYSE",
            company_type="large_cap",
            valuation_model="dcf",
            domicile_country="Switzerland",
        ),
        Company(
            id=5,
            ticker="SINSEC",
            name="SinSec",
            exchange="NYSE",
            company_type="large_cap",
            valuation_model="dcf",
            domicile_country="Canada",
        ),
        Company(
            id=6,
            ticker="SOLO8K",
            name="Solo8K",
            exchange="NYSE",
            company_type="large_cap",
            valuation_model="dcf",
        ),
    ]
    db.add_all(companies)

    def doc(company_id, form):
        return Document(
            company_id=company_id, title=f"{form} {company_id}", source_type="SEC", metadata_={"form": form}
        )

    db.add_all(
        [
            doc(1, "40-F"),
            doc(1, "6-K"),  # BN: FPI canadiense
            doc(2, "10-K"),
            doc(2, "10-Q"),  # AAPL: domestico
            doc(3, "20-F"),  # CGEO.L: FPI
            doc(4, "10-K"),  # Chubb: domicilio fuera, 10-K => NO FPI
            doc(6, "8-K"),  # solo 8-K: no concluyente
        ]
    )
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
    # Contraejemplo del auditor: domicilio fuera de EE. UU. NO es estatus FPI.
    assert client.get("/api/insider/filings", params={"ticker": "CB"}).json()["foreign_issuer"] is False
    # Sin filings SEC guardados o solo formularios no concluyentes: se desconoce
    # la causa, nunca se afirma (aunque el domicilio sea extranjero).
    assert client.get("/api/insider/filings", params={"ticker": "SINSEC"}).json()["foreign_issuer"] is None
    assert client.get("/api/insider/filings", params={"ticker": "SOLO8K"}).json()["foreign_issuer"] is None
    assert client.get("/api/insider/filings", params={"ticker": "NOEXISTE"}).json()["foreign_issuer"] is None
