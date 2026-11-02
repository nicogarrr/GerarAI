"""Sesiones de investigación: claim_ids/source_ids tienen que existir y ser
del usuario (y de la empresa de la sesión). Antes se guardaba cualquier id."""

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.memory import router as memory_router
from app.core.database import Base, get_db
from app.models import Claim, Company, Document, Tenant


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
        mine = Tenant(external_id="sesion-ids-mine", name="Mine")
        other = Tenant(external_id="sesion-ids-other", name="Other")
        db.add_all([mine, other])
        db.flush()
        ids["mine"], ids["other"] = mine.id, other.id
        acme = Company(ticker="ACME", name="Acme", exchange="T", currency="USD",
                       company_type="research_candidate", valuation_model="unassigned")
        beta = Company(ticker="BETA", name="Beta", exchange="T", currency="USD",
                       company_type="research_candidate", valuation_model="unassigned")
        db.add_all([acme, beta])
        db.flush()
        rows = {
            "my_claim": Claim(tenant_id=mine.id, company_id=acme.id, statement="Mine",
                              status="verified", confidence=Decimal("0.7")),
            "my_beta_claim": Claim(tenant_id=mine.id, company_id=beta.id, statement="Beta",
                                   status="verified", confidence=Decimal("0.7")),
            "other_claim": Claim(tenant_id=other.id, company_id=acme.id, statement="Theirs",
                                 status="verified", confidence=Decimal("0.7")),
            "my_doc": Document(tenant_id=mine.id, company_id=acme.id, title="10-K",
                               source_type="sec_filing", source_url="https://sec.gov/a"),
            "other_doc": Document(tenant_id=other.id, company_id=acme.id, title="Theirs",
                                  source_type="sec_filing", source_url="https://sec.gov/b"),
        }
        db.add_all(rows.values())
        db.flush()
        ids.update({name: row.id for name, row in rows.items()})
        db.commit()

    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    def _get_db():
        with factory() as s:
            s.info["tenant_id"] = ids["mine"]
            yield s

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app), ids


def _create(client: TestClient, **extra) -> object:
    body = {"ticker": "ACME", "title": "Review", "question": "Does it hold?"}
    body.update(extra)
    return client.post("/api/memory/research-sessions", json=body)


def test_ids_propios_se_guardan(world):
    client, ids = world
    resp = _create(client, claim_ids=[ids["my_claim"]], source_ids=[ids["my_doc"]])
    assert resp.status_code == 200, resp.text
    assert resp.json()["claim_ids"] == [ids["my_claim"]]
    assert resp.json()["source_ids"] == [ids["my_doc"]]


def test_afirmacion_de_otro_usuario_se_rechaza(world):
    client, ids = world
    assert _create(client, claim_ids=[ids["other_claim"]]).status_code == 404


def test_afirmacion_inexistente_se_rechaza(world):
    client, _ids = world
    assert _create(client, claim_ids=[999_999]).status_code == 404


def test_afirmacion_de_otra_empresa_se_rechaza(world):
    client, ids = world
    assert _create(client, claim_ids=[ids["my_beta_claim"]]).status_code == 404


def test_fuente_de_otro_usuario_o_inexistente_se_rechaza(world):
    client, ids = world
    assert _create(client, source_ids=[ids["other_doc"]]).status_code == 404
    assert _create(client, source_ids=[424_242]).status_code == 404


def test_sin_empresa_vale_cualquier_id_propio(world):
    client, ids = world
    resp = client.post(
        "/api/memory/research-sessions",
        json={"title": "General", "question": "Portfolio review?",
              "claim_ids": [ids["my_claim"], ids["my_beta_claim"]]},
    )
    assert resp.status_code == 200, resp.text
