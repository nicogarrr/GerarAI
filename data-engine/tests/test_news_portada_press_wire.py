"""Portada /api/news: nota de prensa de agencia sin empresa ni carril macro no entra."""

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


def _client(events):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    db = factory()
    db.add(Tenant(id=1, external_id="t"))
    acme = Company(
        ticker="ACME",
        name="ACME Inc",
        exchange="NASDAQ",
        currency="USD",
        company_type="holding",
        valuation_model="unassigned",
    )
    db.add(acme)
    db.flush()
    for event in events(acme.id):
        db.add(event)
    db.commit()

    app = FastAPI()
    app.include_router(news_module.router, prefix="/api/news")

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _event(company_id, title, url, source, metadata=None):
    return NewsEvent(
        tenant_id=1,
        company_id=company_id,
        title=title,
        source=source,
        url=url,
        date=NOW,
        metadata_=metadata or {"connector": "rss", "date_source": "source"},
    )


def test_untagged_press_wire_hidden_from_portada_but_tagged_visible():
    client = _client(
        lambda acme_id: [
            _event(None, "Mariachi Fusion Anthem launches worldwide tour", "https://w.test/1", "PR Newswire"),
            _event(None, "World Food Championships Crown 10 Champions", "https://w.test/2", "All News Releases"),
            _event(acme_id, "Record quarter announced by ACME Inc for shareholders", "https://w.test/3", "PR Newswire"),
            _event(None, "Local bakery opens second location downtown", "https://w.test/4", "City Gazette"),
            _event(
                None,
                "Central banks signal coordinated liquidity stance",
                "https://w.test/5",
                "PR Newswire",
                metadata={"connector": "rss", "date_source": "source", "news_lane": "macro"},
            ),
        ]
    )
    response = client.get("/api/news")
    assert response.status_code == 200
    titles = [row["title"] for row in response.json()]
    assert "Record quarter announced by ACME Inc for shareholders" in titles  # agencia CON empresa: entra
    assert "Local bakery opens second location downtown" in titles  # no agencia: entra
    assert "Central banks signal coordinated liquidity stance" in titles  # carril macro: entra
    assert "Mariachi Fusion Anthem launches worldwide tour" not in titles
    assert "World Food Championships Crown 10 Champions" not in titles


def test_untagged_press_wire_still_visible_in_ticker_view_is_not_applicable():
    # La ficha (?ticker=) filtra por empresa, así que las notas sin empresa
    # nunca aparecen allí; el filtro solo afecta a la portada.
    client = _client(
        lambda acme_id: [
            _event(acme_id, "Record quarter announced by ACME Inc for shareholders", "https://w.test/6", "PR Newswire"),
        ]
    )
    response = client.get("/api/news?ticker=ACME")
    assert response.status_code == 200
    assert [row["title"] for row in response.json()] == [
        "Record quarter announced by ACME Inc for shareholders"
    ]
