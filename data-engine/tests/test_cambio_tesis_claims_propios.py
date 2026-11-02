"""Cambios de tesis manuales: las afirmaciones afectadas (affected_claim_ids)
tienen que existir y ser de la misma empresa (o de ninguna), como en las
sesiones de investigación. Antes se guardaba cualquier id: el cambio salía en
«Qué ha cambiado» de la ficha señalando una afirmación que no existe o de otra
empresa, y un id ajeno bastaba para que el barrido de contradicciones diera esa
afirmación por ya avisada."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.memory import router as memory_router
from app.core.database import Base, get_db
from app.models import Claim, Company, Tenant, ThesisChange


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
        mine = Tenant(external_id="cambio-claims-mine", name="Mine")
        db.add(mine)
        db.flush()
        ids["mine"] = mine.id
        acme = Company(ticker="ACME", name="Acme", exchange="T", currency="USD",
                       company_type="research_candidate", valuation_model="unassigned")
        beta = Company(ticker="BETA", name="Beta", exchange="T", currency="USD",
                       company_type="research_candidate", valuation_model="unassigned")
        db.add_all([acme, beta])
        db.flush()
        acme_claim = Claim(tenant_id=mine.id, company_id=acme.id, statement="Acme crece al 10 %")
        beta_claim = Claim(tenant_id=mine.id, company_id=beta.id, statement="Beta sin deuda neta")
        free_claim = Claim(tenant_id=mine.id, company_id=None, statement="Tipos bajan en 2026")
        db.add_all([acme_claim, beta_claim, free_claim])
        db.flush()
        ids.update(acme=acme.id, beta=beta.id, acme_claim=acme_claim.id,
                   beta_claim=beta_claim.id, free_claim=free_claim.id)
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
    return client.post("/api/memory/thesis/changes", json={"summary": "Cambio manual", **body})


def test_claim_de_otra_empresa_se_rechaza(world):
    client, ids, factory = world
    res = _post(client, ticker="ACME", affected_claim_ids=[ids["beta_claim"]])
    assert res.status_code == 404, res.text
    with factory() as db:
        assert db.query(ThesisChange).count() == 0


def test_claim_inexistente_se_rechaza(world):
    client, ids, factory = world
    res = _post(client, ticker="ACME", affected_claim_ids=[ids["acme_claim"], 999_999])
    assert res.status_code == 404, res.text
    sin_empresa = _post(client, affected_claim_ids=[999_999])
    assert sin_empresa.status_code == 404, sin_empresa.text
    with factory() as db:
        assert db.query(ThesisChange).count() == 0


def test_claims_propios_o_sin_empresa_valen(world):
    client, ids, factory = world
    res = _post(client, ticker="ACME", affected_claim_ids=[ids["acme_claim"], ids["free_claim"]])
    assert res.status_code == 200, res.text
    assert sorted(res.json()["affected_claim_ids"]) == sorted([ids["acme_claim"], ids["free_claim"]])
    # Sin empresa: cualquier afirmación propia que exista.
    libre = _post(client, affected_claim_ids=[ids["beta_claim"]])
    assert libre.status_code == 200, libre.text
    # Sin afirmaciones: sigue valiendo como antes.
    vacio = _post(client, ticker="ACME")
    assert vacio.status_code == 200, vacio.text
