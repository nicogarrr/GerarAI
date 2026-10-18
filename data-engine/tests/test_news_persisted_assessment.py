"""F314: GET /api/news sirve solo lo persistido en ingesta, sin recomputar."""

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import news as news_module
from app.core.database import get_db
from app.models.entities import Base, Company, NewsEvent, Tenant
from app.services.materiality_service import MaterialityService
from app.services.news_service import NewsService

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)

ASSESSMENT_SENTINEL = {
    "source_tier": "tier_1_regulatory",
    "source_trust_score": 1.0,
    "portfolio_weight": 0.42,
    "materiality_reasons": ["persisted_reason"],
    "source_policy": "Regulatoria",
    "model_route": "fast_track",
}


def _make_db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine)


def _client(db):
    app = FastAPI()
    app.include_router(news_module.router, prefix="/api/news")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_ingestion_persists_full_assessment_in_metadata():
    engine, factory = _make_db()
    with factory() as db:
        db.add(Tenant(id=1, external_id="t"))
        db.flush()
        NewsService().analyze_manual_news(
            db,
            "Company files 8-K with the SEC",
            "feed",
            "https://www.sec.gov/Archives/edgar/data/1/x.htm",
        )
        db.commit()
        event = db.query(NewsEvent).one()
        persisted = (event.metadata_ or {}).get("assessment")
        assert persisted is not None
        assert persisted["source_tier"] == "tier_1_regulatory"
        assert persisted["source_trust_score"] == 1.0
        assert persisted["source_policy"]
        assert persisted["model_route"]
        assert isinstance(persisted["portfolio_weight"], float)
        assert persisted["materiality_reasons"]
    engine.dispose()


def test_get_news_serves_persisted_values_without_recompute(monkeypatch):
    def _boom(*args, **kwargs):  # pragma: no cover - solo se ejecuta si hay regresion
        raise AssertionError("GET /api/news no debe recomputar assess_news")

    monkeypatch.setattr(MaterialityService, "assess_news", _boom)
    engine, factory = _make_db()
    with factory() as db:
        db.add(Tenant(id=1, external_id="t"))
        company = Company(
            ticker="ASTS",
            name="AST SpaceMobile",
            exchange="NASDAQ",
            currency="USD",
            company_type="holding",
            valuation_model="unassigned",
        )
        db.add(company)
        db.flush()
        db.add(
            NewsEvent(
                tenant_id=1,
                company_id=company.id,
                title="persisted",
                source="feed",
                url="https://publisher.example/1",
                date=NOW,
                metadata_={"assessment": ASSESSMENT_SENTINEL},
            )
        )
        db.commit()
        response = _client(db).get("/api/news")
        assert response.status_code == 200, response.text
        row = response.json()[0]
        assert row["source_tier"] == "tier_1_regulatory"
        assert row["source_trust_score"] == 1.0
        assert row["portfolio_weight"] == 0.42
        assert row["materiality_reasons"] == ["persisted_reason"]
        assert row["source_policy"] == "Regulatoria"
        assert row["model_route"] == "fast_track"
    engine.dispose()


def test_get_news_legacy_event_without_assessment_returns_honest_nulls(monkeypatch):
    def _boom(*args, **kwargs):  # pragma: no cover
        raise AssertionError("GET /api/news no debe recomputar assess_news")

    monkeypatch.setattr(MaterialityService, "assess_news", _boom)
    engine, factory = _make_db()
    with factory() as db:
        db.add(Tenant(id=1, external_id="t"))
        db.flush()
        db.add(
            NewsEvent(
                tenant_id=1,
                company_id=None,
                title="legacy",
                source="rss",
                url="https://publisher.example/2",
                date=NOW,
                metadata_={"connector": "rss", "date_source": "source"},
            )
        )
        db.commit()
        response = _client(db).get("/api/news")
        assert response.status_code == 200, response.text
        row = response.json()[0]
        assert row["source_tier"] is None
        assert row["source_trust_score"] is None
        assert row["portfolio_weight"] is None
        assert row["materiality_reasons"] is None
        assert row["source_policy"] is None
        assert row["model_route"] is None
    engine.dispose()


def test_legacy_solicitation_projects_low_materiality_without_changing_storage():
    engine, factory = _make_db()
    with factory() as db:
        db.add(Tenant(id=1, external_id="t"))
        titles = ["ASTS SHAREHOLDER ALERT: Bronstein invites investors", "ASTS Deadline in 26 Days: Class Action reminder", "AST SpaceMobile settles securities class action"]
        for title in titles:
            db.add(NewsEvent(tenant_id=1, title=title, summary=title, source="prnewswire/GDELT", date=NOW, materiality_score=3, requires_update=True))
        db.commit()
        rows = {row["title"]: row for row in _client(db).get("/api/news").json()}
        for title in titles[:2]:
            assert rows[title]["materiality_score"] == 1
            assert rows[title]["event_type"] == "legal_solicitation"
            assert rows[title]["requires_update"] is False
        assert rows[titles[2]]["materiality_score"] == 3
        assert rows[titles[2]]["requires_update"] is True
        assert all(event.materiality_score == 3 for event in db.query(NewsEvent).all())
    engine.dispose()
