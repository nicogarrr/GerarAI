"""Filtro ?tickers= (carril «Para ti»: cartera + watchlist del usuario)."""

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import news as news_module
from app.core.database import get_db
from app.models.entities import Base, Company, NewsEvent, Tenant

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)


def _client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(engine)()
    db.add(Tenant(id=1, external_id="t"))
    names = {"ASTS": "AST SpaceMobile", "META": "Meta Platforms", "NVDA": "NVIDIA Corp"}
    for ticker, name in names.items():
        db.add(Company(ticker=ticker, name=name, exchange="NASDAQ", currency="USD",
                       company_type="holding", valuation_model="unassigned"))
    db.flush()
    for ticker, i in (("ASTS", 1), ("META", 2), ("NVDA", 3)):
        company = db.query(Company).filter_by(ticker=ticker).one()
        db.add(NewsEvent(tenant_id=1, company_id=company.id,
                         title=f"{names[ticker]} announces quarterly results today", source="rss",
                         url=f"https://p.example/{ticker}{i}", date=NOW,
                         metadata_={"date_source": "source"}))
    db.add(NewsEvent(tenant_id=1, company_id=None, title="macro event", source="GDELT",
                     url="https://p.example/m1", date=NOW,
                     metadata_={"news_lane": "macro", "macro_theme": "ormuz"}))
    db.commit()
    app = FastAPI()
    app.include_router(news_module.router, prefix="/api/news")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_tickers_filtra_a_las_empresas_pedidas():
    body = _client().get("/api/news", params={"tickers": "ASTS,META"}).json()
    assert {row["ticker"] for row in body} == {"ASTS", "META"}


def test_tickers_sin_empresa_macro_no_entra():
    body = _client().get("/api/news", params={"tickers": "ASTS,META,NVDA"}).json()
    assert all(row["news_lane"] != "macro" for row in body)
    assert len(body) == 3


def test_tickers_case_insensitive_y_espacios():
    body = _client().get("/api/news", params={"tickers": " asts , meta "}).json()
    assert {row["ticker"] for row in body} == {"ASTS", "META"}


def test_tickers_vacio_o_basura_no_devuelve_nada():
    assert _client().get("/api/news", params={"tickers": ";;;"}).json() == []


def test_tickers_no_limita_si_no_se_pasa():
    body = _client().get("/api/news", params={"lane": "macro"}).json()
    assert len(body) == 1
