"""Paginacion y filtro de carril de /api/news (scroll infinito)."""

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import news as news_module
from app.core.database import get_db
from app.models.entities import Base, Company, NewsEvent, Tenant

# Relativa a ahora: la ruta filtra frescura real (macro 72 h) contra el reloj
# del sistema; una fecha fija (27-sep) quedó vieja y el carril macro devolvía 0.
NOW = datetime.now(UTC)


def _client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(engine)()
    db.add(Tenant(id=1, external_id="t"))
    company = Company(ticker="ASTS", name="AST", exchange="NASDAQ", currency="USD",
                      company_type="holding", valuation_model="unassigned")
    db.add(company)
    db.flush()
    for i in range(5):
        db.add(NewsEvent(tenant_id=1, company_id=company.id, title=f"emp {i}", source="rss",
                         url=f"https://p.example/e{i}", date=NOW - timedelta(hours=i),
                         metadata_={"date_source": "source"}))
    for i in range(3):
        db.add(NewsEvent(tenant_id=1, company_id=None, title=f"mac {i}", source="GDELT",
                         url=f"https://p.example/m{i}", date=NOW - timedelta(minutes=i * 7),
                         metadata_={"news_lane": "macro", "macro_theme": "ormuz"}))
    db.commit()
    app = FastAPI()
    app.include_router(news_module.router, prefix="/api/news")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_pages_do_not_overlap_and_cover_all():
    client = _client()
    first = client.get("/api/news", params={"limit": 3, "offset": 0}).json()
    second = client.get("/api/news", params={"limit": 3, "offset": 3}).json()
    third = client.get("/api/news", params={"limit": 3, "offset": 6}).json()
    ids = [r["id"] for r in first + second + third]
    assert len(first) == 3 and len(second) == 3 and len(third) == 2
    assert len(set(ids)) == 8


def test_lane_filter_is_applied_in_sql():
    client = _client()
    macro = client.get("/api/news", params={"lane": "macro"}).json()
    empresa = client.get("/api/news", params={"lane": "empresa", "limit": 2}).json()
    assert {r["news_lane"] for r in macro} == {"macro"} and len(macro) == 3
    assert all(r["ticker"] == "ASTS" for r in empresa) and len(empresa) == 2


def test_invalid_params_rejected():
    client = _client()
    assert client.get("/api/news", params={"limit": 0}).status_code == 422
    assert client.get("/api/news", params={"limit": 101}).status_code == 422
    assert client.get("/api/news", params={"offset": -1}).status_code == 422
    assert client.get("/api/news", params={"lane": "otro"}).status_code == 422
