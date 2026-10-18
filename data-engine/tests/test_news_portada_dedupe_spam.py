"""Portada /api/news: dedupe de titulares literales y filtro de spam legal."""

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import news as news_module
from app.core.database import get_db
from app.models.entities import Base, Company, NewsEvent, Tenant

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
SPAM_TITLE = "SHAREHOLDER ALERT: Pomerantz Law Firm Investigates Claims on Behalf of Investors"


def _company(ticker: str) -> Company:
    return Company(
        ticker=ticker,
        name=f"{ticker} Inc",
        exchange="NASDAQ",
        currency="USD",
        company_type="holding",
        valuation_model="unassigned",
    )


def _event(company_id, title, url, **kw):
    return NewsEvent(
        tenant_id=1,
        company_id=company_id,
        title=title,
        source="rss",
        url=url,
        date=kw.pop("date", NOW),
        metadata_={"connector": "rss", "date_source": "source"},
        **kw,
    )


def _client(events):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    db = factory()
    db.add(Tenant(id=1, external_id="t"))
    acme = _company("ACME")
    db.add(acme)
    db.flush()
    for event in events(acme.id):
        db.add(event)
    db.commit()

    app = FastAPI()
    app.include_router(news_module.router, prefix="/api/news")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_portada_dedupa_titulares_literales():
    def events(cid):
        return [
            _event(cid, "Acme beats expectations", "https://pub.example/1"),
            _event(cid, "Acme beats expectations", "https://pub.example/2"),
            _event(cid, "  acme beats expectations ", "https://pub.example/3"),
            _event(cid, "Otra noticia distinta", "https://pub.example/4"),
        ]

    client = _client(events)
    body = client.get("/api/news").json()
    titles = [row["title"] for row in body]
    assert len([t for t in titles if t.strip().lower() == "acme beats expectations"]) == 1
    assert "Otra noticia distinta" in titles


def test_portada_filtra_spam_legal():
    def events(cid):
        return [
            _event(cid, SPAM_TITLE, "https://pub.example/10"),
            _event(cid, "Acme beats expectations", "https://pub.example/11"),
        ]

    client = _client(events)
    titles = [row["title"] for row in client.get("/api/news").json()]
    assert SPAM_TITLE not in titles
    assert "Acme beats expectations" in titles


def test_ficha_empresa_conserva_spam_legal_etiquetado():
    def events(cid):
        return [
            _event(cid, SPAM_TITLE, "https://pub.example/20"),
            _event(cid, "Acme beats expectations", "https://pub.example/21"),
        ]

    client = _client(events)
    body = client.get("/api/news?ticker=ACME").json()
    spam = [row for row in body if row["title"] == SPAM_TITLE]
    assert len(spam) == 1, "en la ficha de la empresa la solicitud se conserva"
    assert spam[0]["event_type"] == "legal_solicitation"
