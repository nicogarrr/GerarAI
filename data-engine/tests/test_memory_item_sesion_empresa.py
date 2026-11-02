"""Notas de memoria: la sesión de investigación enlazada tiene que ser de la
misma empresa que la nota (o de ninguna). Antes una nota de BETA se colgaba de
una sesión de ACME y aparecía en ella."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.memory import router as memory_router
from app.core.database import Base, get_db
from app.models import Company, MemoryItem, ResearchSession, Tenant


@pytest.fixture
def world():
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    ids: dict[str, int] = {}
    with factory() as db:
        mine = Tenant(external_id="memoria-sesion-mine", name="Mine")
        db.add(mine)
        db.flush()
        ids["mine"] = mine.id
        acme = Company(ticker="ACME", name="Acme", exchange="T", currency="USD",
                       company_type="research_candidate", valuation_model="unassigned")
        beta = Company(ticker="BETA", name="Beta", exchange="T", currency="USD",
                       company_type="research_candidate", valuation_model="unassigned")
        db.add_all([acme, beta])
        db.flush()
        acme_session = ResearchSession(tenant_id=mine.id, company_id=acme.id, title="Acme",
                                       question="¿Foso?", status="open")
        free_session = ResearchSession(tenant_id=mine.id, company_id=None, title="Cartera",
                                       question="¿Riesgo?", status="open")
        db.add_all([acme_session, free_session])
        db.flush()
        ids.update(acme=acme.id, beta=beta.id, acme_session=acme_session.id,
                   free_session=free_session.id)
        db.commit()

    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    def _get_db():
        with factory() as s:
            s.info["tenant_id"] = ids["mine"]
            yield s

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app), ids, factory


def _post(client, **body):
    return client.post("/api/memory/memory-items", json={"content": "Nota de prueba", **body})


def test_nota_de_otra_empresa_no_se_cuelga_de_la_sesion(world):
    client, ids, factory = world
    res = _post(client, ticker="BETA", scope="company", research_session_id=ids["acme_session"])
    assert res.status_code == 404
    with factory() as db:
        assert db.query(MemoryItem).count() == 0
        session = db.get(ResearchSession, ids["acme_session"])
        assert session is not None and session.memory_item_ids == []


def test_nota_de_otra_empresa_por_company_id_tambien(world):
    client, ids, _ = world
    res = _post(client, company_id=ids["beta"], scope="company",
                research_session_id=ids["acme_session"])
    assert res.status_code == 404


def test_nota_de_la_misma_empresa_si_se_cuelga(world):
    client, ids, factory = world
    res = _post(client, ticker="ACME", scope="company", research_session_id=ids["acme_session"])
    assert res.status_code == 200, res.text
    item_id = res.json()["id"]
    with factory() as db:
        session = db.get(ResearchSession, ids["acme_session"])
        assert session is not None and session.memory_item_ids == [item_id]


def test_sesion_sin_empresa_admite_cualquier_nota(world):
    client, ids, _ = world
    res = _post(client, ticker="BETA", scope="company", research_session_id=ids["free_session"])
    assert res.status_code == 200, res.text


def test_nota_sin_empresa_en_sesion_de_empresa_sigue_valiendo(world):
    client, ids, _ = world
    res = _post(client, research_session_id=ids["acme_session"])
    assert res.status_code == 200, res.text
