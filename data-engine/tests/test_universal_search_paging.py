"""POST /api/search honra `page`: la página 2 no repite la 1 y el total es real."""

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.search import router as search_router
from app.core.database import Base, get_db
from app.models import Claim, Company, Tenant


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        tenant = Tenant(external_id="paging-test", name="Paging test")
        session.add(tenant)
        session.flush()
        tenant_id = tenant.id
        session.info["tenant_id"] = tenant_id
        company = Company(
            ticker="PAGE",
            name="Paging Co",
            exchange="TEST",
            currency="USD",
            company_type="research_candidate",
            valuation_model="unassigned",
        )
        session.add(company)
        session.flush()
        for i in range(5):
            session.add(
                Claim(
                    company_id=company.id,
                    statement=f"Capital allocation discipline note number {i}.",
                    status="verified",
                    confidence=Decimal("0.8"),
                )
            )
        session.commit()

    app = FastAPI()
    app.include_router(search_router, prefix="/api/search")

    def _get_db():
        with factory() as s:
            s.info["tenant_id"] = tenant_id
            yield s

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def _page(client: TestClient, page: int, page_size: int = 2) -> dict:
    resp = client.post(
        "/api/search",
        json={
            "query": "capital allocation discipline",
            "page": page,
            "page_size": page_size,
            "include_vector": False,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_la_pagina_dos_no_repite_la_primera(client: TestClient):
    first = _page(client, 1)
    second = _page(client, 2)
    third = _page(client, 3)
    ids = [[item["citation"] for item in body["items"]] for body in (first, second, third)]
    assert [len(chunk) for chunk in ids] == [2, 2, 1]
    flat = [c for chunk in ids for c in chunk]
    assert len(set(flat)) == 5


def test_page_info_cuenta_todos_los_resultados(client: TestClient):
    first = _page(client, 1)
    assert first["page_info"]["total_items"] == 5
    assert first["page_info"]["total_pages"] == 3
    assert first["page_info"]["has_next"] is True
    last = _page(client, 3)
    assert last["page_info"]["has_next"] is False
    assert last["page_info"]["has_prev"] is True


def test_pagina_mas_alla_del_final_viene_vacia(client: TestClient):
    beyond = _page(client, 9)
    assert beyond["items"] == []
    assert beyond["page_info"]["total_items"] == 5


def test_una_sola_pagina_conserva_el_orden_de_siempre(client: TestClient):
    whole = _page(client, 1, page_size=20)
    paged = _page(client, 1)["items"] + _page(client, 2)["items"] + _page(client, 3)["items"]
    assert [i["citation"] for i in whole["items"]] == [i["citation"] for i in paged]
