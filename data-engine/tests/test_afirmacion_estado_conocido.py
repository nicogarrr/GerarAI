"""Afirmaciones: el estado tiene que ser uno de los que la app entiende, como
en notas de memoria y sesiones de investigación. Antes se guardaba cualquier
texto («Supported», «verificada», «1e999»): la afirmación salía «con estado
desconocido» y no contaba ni como pendiente ni como respaldada. Y filtrar la
lista por un estado mal escrito devolvía una lista vacía sin avisar."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.memory import router as memory_router
from app.core.database import Base, get_db
from app.models import Claim, Company, Tenant

ESTADOS = ("unverified", "supported", "contradicted", "superseded", "stale", "uncertain")


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
        mine = Tenant(external_id="estado-afirmacion-mine", name="Mine")
        db.add(mine)
        db.flush()
        ids["mine"] = mine.id
        db.add(Company(ticker="ACME", name="Acme", exchange="T", currency="USD",
                       company_type="research_candidate", valuation_model="unassigned"))
        db.commit()

    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    def _get_db():
        with factory() as s:
            s.info["tenant_id"] = ids["mine"]
            yield s

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app), factory


@pytest.mark.parametrize("status", ["Supported", "verificada", "1e999", " ", "open"])
def test_estado_desconocido_se_rechaza(world, status):
    client, factory = world
    res = client.post("/api/memory/claims",
                      json={"ticker": "ACME", "statement": "Acme crece al 10 %", "status": status})
    assert res.status_code == 400, res.text
    with factory() as db:
        assert db.query(Claim).count() == 0


def test_estados_conocidos_valen(world):
    client, _ = world
    for status in ESTADOS:
        res = client.post("/api/memory/claims",
                          json={"ticker": "ACME", "statement": f"Afirmación {status}", "status": status})
        assert res.status_code == 200, (status, res.text)
        assert res.json()["status"] == status
    # Sin estado: sigue entrando como pendiente.
    res = client.post("/api/memory/claims", json={"ticker": "ACME", "statement": "Sin estado"})
    assert res.status_code == 200 and res.json()["status"] == "unverified"


def test_filtro_por_estado(world):
    client, _ = world
    client.post("/api/memory/claims", json={"ticker": "ACME", "statement": "Margen estable"})
    ok = client.get("/api/memory/claims", params={"status": "unverified"})
    assert ok.status_code == 200 and len(ok.json()) == 1
    bad = client.get("/api/memory/claims", params={"status": "pendiente"})
    assert bad.status_code == 400, bad.text
    todos = client.get("/api/memory/claims")
    assert todos.status_code == 200 and len(todos.json()) == 1
