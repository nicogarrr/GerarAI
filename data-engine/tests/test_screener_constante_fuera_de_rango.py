"""Un número fuera de rango en una fórmula del screener se rechaza al guardarla.

«1e999» llega a ast como float('inf'): el filtro «pe_ratio < 1e999» se guardaba
(201) y después ninguna empresa podía evaluarse («resultado no finito»), sin
aviso. «1e-400» llega como 0.0 y comparaba contra un 0 que nadie escribió.
Mismo criterio que los umbrales de alertas y de la tesis (#4166, #4170, #4185).
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import screeners
from app.core.database import Base, get_db
from app.models import Tenant
from app.services.screener_service import SafeFormula


@pytest.mark.parametrize(
    "expression",
    ["1e999", "-1e999", "pe_ratio * 1e999", "1e999 - 1e999", "1e-400", "pe_ratio + 1e-400", "1E-999"],
)
def test_out_of_range_literal_is_rejected(expression):
    with pytest.raises(ValueError, match="fuera de rango"):
        SafeFormula.reject_out_of_range(expression)
    # Una fórmula ya guardada con ese número sigue cargando (no rompe la corrida).
    assert SafeFormula(expression).out_of_range


@pytest.mark.parametrize(
    "expression", ["0", "0.0", "0e5", "1e308", "1e-300", "pe_ratio * 0.5", "-0.0", "1_000.5", " 1e3 "]
)
def test_in_range_literals_still_valid(expression):
    SafeFormula.reject_out_of_range(expression)
    assert not SafeFormula(expression).out_of_range


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        tenant = Tenant(external_id="t", name="T")
        db.add(tenant)
        db.commit()
        tenant_id = tenant.id

    def _db():
        with factory() as session:
            session.info["tenant_id"] = tenant_id
            yield session

    app = FastAPI()
    app.include_router(screeners.router, prefix="/screeners")
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def test_saved_screen_with_infinite_threshold_is_rejected(client):
    response = client.post(
        "/screeners/screens",
        json={"name": "Barato", "criteria": [{"left": "pe_ratio", "operator": "<", "right": "1e999"}]},
    )
    assert response.status_code == 400
    assert "fuera de rango" in response.json()["detail"]
    assert client.get("/screeners/screens").json() == []


def test_custom_metric_with_infinite_constant_is_rejected(client):
    response = client.post(
        "/screeners/custom-metrics",
        json={"metric_key": "enorme", "name": "Enorme", "formula": "pe_ratio * 1e999"},
    )
    assert response.status_code == 400
    assert client.get("/screeners/custom-metrics").json() == []


def test_ad_hoc_run_with_infinite_threshold_is_rejected(client):
    response = client.post(
        "/screeners/run",
        json={"criteria": [{"left": "pe_ratio", "operator": "<", "right": "1e999"}]},
    )
    assert response.status_code == 400
    assert "fuera de rango" in response.json()["detail"]


def test_update_screen_with_infinite_ranking_is_rejected(client):
    created = client.post(
        "/screeners/screens",
        json={"name": "Barato", "criteria": [{"left": "pe_ratio", "operator": "<", "right": "15"}]},
    )
    assert created.status_code == 201
    screen_id = created.json()["id"]
    response = client.put(
        f"/screeners/screens/{screen_id}",
        json={
            "name": "Barato",
            "criteria": [{"left": "pe_ratio", "operator": "<", "right": "15"}],
            "ranking_formula": "pe_ratio * 1e-400",
        },
    )
    assert response.status_code == 400
    assert client.get("/screeners/screens").json()[0]["ranking_formula"] is None


def test_saved_screen_stored_before_with_infinite_threshold_still_runs(client):
    created = client.post(
        "/screeners/screens",
        json={"name": "Antiguo", "criteria": [{"left": "pe_ratio", "operator": "<", "right": "15"}]},
    )
    screen_id = created.json()["id"]
    db = next(client.app.dependency_overrides[get_db]())
    from app.models import SavedScreen

    screen = db.get(SavedScreen, screen_id)
    screen.criteria = [{"left": "pe_ratio", "operator": "<", "right": "1e999"}]
    db.commit()
    response = client.post(f"/screeners/screens/{screen_id}/run")
    assert response.status_code == 200
    assert response.json()["match_count"] == 0
