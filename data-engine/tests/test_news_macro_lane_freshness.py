"""Carril macro: la lectura acota frescura (72 h); las filas viejas no salen."""

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import news as news_module
from app.core.database import get_db
from app.models.entities import Base, NewsEvent, Tenant

NOW = datetime.now(UTC)


def _macro_event(title, url, date):
    return NewsEvent(
        tenant_id=1,
        company_id=None,
        title=title,
        source="gdelt",
        url=url,
        date=date,
        metadata_={"connector": "gdelt", "date_source": "source", "news_lane": "macro",
                   "macro_theme": "gold_central_banks"},
    )


def _client():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    db = factory()
    db.add(Tenant(id=1, external_id="t"))
    db.add(_macro_event("Fresh macro headline", "https://g.example/fresh", NOW - timedelta(hours=5)))
    db.add(_macro_event("Stale macro headline", "https://g.example/stale", NOW - timedelta(days=10)))
    db.commit()

    app = FastAPI()
    app.include_router(news_module.router, prefix="/api/news")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_macro_lane_excluye_items_de_mas_de_72h():
    body = _client().get("/api/news?lane=macro").json()
    titles = [row["title"] for row in body]
    assert "Fresh macro headline" in titles
    assert "Stale macro headline" not in titles
