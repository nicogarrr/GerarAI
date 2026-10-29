"""Serializacion del carril de noticias en /api/news: macro GDELT vs empresa."""

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import news as news_module
from app.core.database import get_db
from app.models.entities import Base, Company, NewsEvent, Tenant

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)


def test_news_events_serialize_macro_lane_and_theme():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add(Tenant(id=1, external_id="t"))
        company = Company(ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ",
                          currency="USD", company_type="holding", valuation_model="unassigned")
        db.add(company)
        db.flush()
        db.add_all([
            NewsEvent(tenant_id=1, company_id=company.id, title="company news", source="rss",
                      url="https://publisher.example/1", date=NOW,
                      metadata_={"connector": "rss", "date_source": "source"}),
            NewsEvent(tenant_id=1, company_id=None, title="macro news", source="GDELT",
                      url="https://publisher.example/2", date=NOW,
                      metadata_={"connector": "gdelt", "date_source": "gdelt_first_seen",
                                 "news_lane": "macro", "macro_theme": "ormuz"}),
        ])
        db.add_all([
            NewsEvent(tenant_id=1, company_id=company.id, title="retired social post", source="Social conversation",
                      url="https://social.example/message/1", date=NOW,
                      metadata_={"news_lane": "social"}),
            NewsEvent(tenant_id=1, company_id=None, title="official government release", source="Fed official",
                      url="https://official.example/release/1", date=NOW,
                      metadata_={"news_lane": "gobierno"}),
        ])
        db.commit()

        app = FastAPI()
        app.include_router(news_module.router, prefix="/api/news")

        def _override_db():
            yield db

        app.dependency_overrides[get_db] = _override_db
        client = TestClient(app)
        response = client.get("/api/news")
        assert response.status_code == 200, response.text
        rows = {row["title"]: row for row in response.json()}
        assert "retired social post" not in rows
        assert client.get("/api/news?lane=social").status_code == 422
        assert {row["title"] for row in client.get("/api/news?lane=gobierno").json()} == {"official government release"}
        assert "retired social post" not in {row["title"] for row in client.get("/api/news?ticker=ASTS").json()}
        # Stored history is preserved, not deleted by the read path.
        assert db.query(NewsEvent).filter(NewsEvent.title == "retired social post").count() == 1
        # evento de empresa: sin carril macro
        assert rows["company news"]["news_lane"] is None
        assert rows["company news"]["macro_theme"] is None
        # evento macro GDELT: carril y tema serializados para el filtro UI
        assert rows["macro news"]["news_lane"] == "macro"
        assert rows["macro news"]["macro_theme"] == "ormuz"
        assert rows["macro news"]["ticker"] is None
    engine.dispose()
