"""Vínculo «sobre»/«relacionada» en la respuesta de /api/news y fixture de
otras empresas sembradas (NVDA, AMD, TSLA, RKLB, MSFT, META, AMZN, NVO, CCJ...)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import news as news_module
from app.core.database import get_db
from app.models.entities import Base, Company, NewsEvent, Tenant
from app.services.news_service import NewsService
from tests.test_news_aliases_asts import db  # noqa: F401  (fixture)

FIXTURE = Path(__file__).parent / "fixtures" / "news_links" / "otros_v1.json"
NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


def _otros():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["casos"]


@pytest.mark.parametrize("caso", _otros(), ids=lambda c: c["texto"][:40])
def test_otras_empresas_sembradas(db, caso):  # noqa: F811
    primary, related = NewsService().detect_company_links(db, caso["texto"])
    tipo = caso["tipo"]
    if tipo is None:
        assert primary is None and related == []
    elif tipo.startswith("anotada:"):
        assert primary is None
        assert sorted(r.company.ticker for r in related) == sorted(tipo.split(":", 1)[1].split(","))
        assert all(r.link_type == "relacionada" for r in related)
    else:
        assert primary is not None
        assert (primary.company.ticker, primary.link_type) == (caso["ticker"], tipo)


def test_api_expone_vinculo_y_relacionadas():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        session.add(Tenant(id=1, external_id="t"))
        asts = Company(
            ticker="ASTS",
            name="AST SpaceMobile",
            exchange="NASDAQ",
            currency="USD",
            company_type="holding",
            valuation_model="unassigned",
        )
        session.add(asts)
        session.flush()
        vinculo = {"ticker": "ASTS", "tipo": "relacionada", "via": "socio:Verizon"}
        session.add_all(
            [
                NewsEvent(
                    tenant_id=1,
                    company_id=asts.id,
                    title="Verizon expands direct-to-cell satellite plans",
                    source="rss",
                    url="https://publisher.example/vz",
                    date=NOW,
                    metadata_={"vinculo": vinculo},
                ),
                NewsEvent(
                    tenant_id=1,
                    company_id=asts.id,
                    title="AST SpaceMobile (ASTS) raises capital",
                    source="rss",
                    url="https://publisher.example/asts",
                    date=NOW,
                    metadata_={},
                ),
            ]
        )
        session.commit()
        app = FastAPI()
        app.include_router(news_module.router, prefix="/api/news")

        def _override_db():
            yield session

        app.dependency_overrides[get_db] = _override_db
        response = TestClient(app).get("/api/news?ticker=ASTS")
        assert response.status_code == 200, response.text
        rows = {row["title"]: row for row in response.json()}
        assert rows["Verizon expands direct-to-cell satellite plans"]["vinculo"] == vinculo
        assert rows["AST SpaceMobile (ASTS) raises capital"]["vinculo"] is None
        assert rows["AST SpaceMobile (ASTS) raises capital"]["relacionadas"] is None
