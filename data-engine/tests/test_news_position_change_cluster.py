"""Portada /api/news: agrupación de titulares boilerplate 13F (MarketBeat)."""

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
    amzn = Company(
        ticker="AMZN",
        name="Amazon.com Inc",
        exchange="NASDAQ",
        currency="USD",
        company_type="holding",
        valuation_model="unassigned",
    )
    db.add(amzn)
    db.flush()
    for event in events(amzn.id):
        db.add(event)
    db.commit()

    app = FastAPI()
    app.include_router(news_module.router, prefix="/api/news")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_portada_agrupa_titulares_boilerplate_13f():
    def events(cid):
        return [
            _event(
                cid,
                "Vanguard Group Inc. Purchases 12,345 Shares of Amazon.com, Inc. (AMZN)",
                "https://mb.example/1",
            ),
            _event(
                cid,
                "Amazon.com, Inc. (AMZN) Shares Purchased by Smith Salley Wealth Management",
                "https://mb.example/2",
            ),
            _event(
                cid,
                "Wealth Enhancement Advisory Services LLC Buys 3,456 Shares of Amazon.com (AMZN)",
                "https://mb.example/3",
            ),
            _event(cid, "Amazon beats expectations in Q3", "https://mb.example/4"),
        ]

    body = _client(events).get("/api/news").json()
    cluster_rows = [row for row in body if row.get("cluster_count")]
    assert len(cluster_rows) == 1
    row = cluster_rows[0]
    assert row["cluster_count"] == 3
    assert "3 movimientos de inversores institucionales en AMZN" in row["title"]
    assert row["headline_from_source"] is False
    # Un titular real de la misma empresa y día no se absorbe en el grupo.
    assert any(r["title"] == "Amazon beats expectations in Q3" for r in body)


def test_ficha_empresa_no_agrupa_movimientos_13f():
    def events(cid):
        return [
            _event(
                cid,
                "Vanguard Group Inc. Purchases 12,345 Shares of Amazon.com, Inc. (AMZN)",
                "https://mb.example/10",
            ),
            _event(
                cid,
                "Amazon.com, Inc. (AMZN) Shares Purchased by Smith Salley Wealth Management",
                "https://mb.example/11",
            ),
        ]

    body = _client(events).get("/api/news?ticker=AMZN").json()
    assert len(body) == 2
    assert all(not row.get("cluster_count") for row in body)
