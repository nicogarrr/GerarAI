"""Endpoints /companies/{ticker}/inferred-inputs: 422 con URLs invalidas y
aislamiento tenant (lo creado en el tenant 1 no existe para el tenant 2)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.companies import router
from app.core.database import get_db
from app.models.entities import Base, Company
from app.services.inferred_input_service import InferredInputService

BASE = "Dado el guidance de despliegue y los contratos firmados, inferimos margen FCF positivo"
URL = "https://www.sec.gov/Archives/edgar/data/1780312/x.htm"


@pytest.fixture()
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions: dict[int, Session] = {}

    def session_for(tenant: int) -> Session:
        if tenant not in sessions:
            s = Session(engine)
            s.info["tenant_id"] = tenant
            sessions[tenant] = s
        return sessions[tenant]

    seed = session_for(1)
    seed.add(Company(ticker="BRN", name="Burn", exchange="NASDAQ", company_type="growth",
                     valuation_model="pre_revenue"))
    seed.commit()
    current = {"tenant": 1}
    app = FastAPI()
    app.include_router(router, prefix="/companies")
    app.dependency_overrides[get_db] = lambda: session_for(current["tenant"])
    yield TestClient(app), current, session_for
    for s in sessions.values():
        s.close()
    engine.dispose()


def _body(**over):
    body = {"input_key": "fcf_margin", "value": "-0.2", "base": BASE, "source_urls": [URL]}
    body.update(over)
    return body


def test_valid_post_201_and_get(env):
    client, _, _ = env
    res = client.post("/companies/BRN/inferred-inputs", json=_body())
    assert res.status_code == 201, res.text
    assert res.json()["source_urls"] == [URL]
    assert len(client.get("/companies/BRN/inferred-inputs").json()) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://user.name@localhost/x",
        "https://user:pass@example.com/a",
        "https://.",
        "https://example.com:bad/x",
        "http://example.com/x",
    ],
)
def test_invalid_or_credentialed_urls_422_and_nothing_stored(env, url):
    client, _, _ = env
    res = client.post("/companies/BRN/inferred-inputs", json=_body(source_urls=[url]))
    assert res.status_code == 422
    assert "pass" not in res.text
    assert client.get("/companies/BRN/inferred-inputs").json() == []


def test_short_base_or_out_of_range_422(env):
    client, _, _ = env
    assert client.post("/companies/BRN/inferred-inputs", json=_body(base="corta")).status_code == 422
    assert client.post("/companies/BRN/inferred-inputs", json=_body(value="5")).status_code == 422


def test_tenant_isolation_on_read(env):
    client, current, session_for = env
    assert client.post("/companies/BRN/inferred-inputs", json=_body()).status_code == 201
    company = session_for(1).query(Company).filter_by(ticker="BRN").one()
    assert InferredInputService().latest_valid(session_for(1), company.id, "fcf_margin")
    current["tenant"] = 2
    assert InferredInputService().latest_valid(session_for(2), company.id, "fcf_margin") is None
    # Company remains global; private inferences do not cross the boundary.
    other = client.get("/companies/BRN/inferred-inputs")
    assert other.status_code == 200 and other.json() == []
    current["tenant"] = 1
    assert len(client.get("/companies/BRN/inferred-inputs").json()) == 1
