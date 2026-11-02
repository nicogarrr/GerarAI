"""Criterio de invalidación con un umbral que desborda el float («1e400»).

``Decimal("1e400")`` es finito, pero se guarda como ``float`` (infinito): el
criterio quedaba guardado con umbral ``null`` («precio < Infinity»), sin
vigilancia, y en Postgres el JSON con ``Infinity`` rompe el guardado (500).
Ahora se rechaza como cualquier umbral no finito."""

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.thesis import router as thesis_router
from app.core.database import Base, get_db
from app.models.entities import Company, Tenant, ThesisVersion
from app.services.thesis_invalidation_rules import normalize_rules


@pytest.mark.parametrize("threshold", ["1e400", "-1e400", "1E+999"])
def test_umbral_que_desborda_float_se_rechaza(threshold):
    with pytest.raises(ValueError) as exc:
        normalize_rules([{"metric": "precio", "operator": "<", "threshold": threshold}])
    assert "Criterio 1" in str(exc.value)


def test_umbral_grande_pero_representable_se_acepta():
    rules = normalize_rules([{"metric": "precio", "operator": "<", "threshold": "1e300"}])
    assert rules[0]["threshold"] == 1e300


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        tenant = Tenant(external_id="umbral-infinito", name="Umbral")
        db.add(tenant)
        db.flush()
        tenant_id = tenant.id
        db.info["tenant_id"] = tenant_id
        company = Company(ticker="POOL", name="Pool", exchange="NASDAQ", currency="USD",
                          company_type="holding", valuation_model="unassigned")
        db.add(company)
        db.flush()
        db.add(ThesisVersion(
            company_id=company.id, version=1, status="final", thesis_markdown="# Tesis",
            executive_summary="Resumen", rating="watch", current_price=Decimal("300"),
            expected_value=Decimal("400"), invalidation_criteria=[],
        ))
        db.commit()

    app = FastAPI()
    app.include_router(thesis_router, prefix="/api/thesis")

    def _get_db():
        with factory() as s:
            s.info["tenant_id"] = tenant_id
            yield s

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def test_put_con_umbral_desbordado_es_422_y_no_guarda(client):
    resp = client.put("/api/thesis/POOL/invalidation-rules",
                      json={"rules": [{"metric": "precio", "operator": "<", "threshold": "1e400"}]})
    assert resp.status_code == 422, resp.text
    assert "umbral" in resp.json()["detail"]
    saved = client.get("/api/thesis/POOL/invalidation-rules")
    if saved.status_code == 200:
        assert not saved.json().get("invalidation_rules")
