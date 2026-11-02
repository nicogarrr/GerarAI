"""Lecciones del diario, promesas de la dirección y supuestos de la tesis:
``min_length`` contaba espacios, así que «     » pasaba la validación y se
guardaba un texto vacío (el servicio recorta). Ahora es 422."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.companies import router as companies_router
from app.api.routes.thesis import router as thesis_router
from app.core.database import Base, get_db
from app.models import (
    Company,
    DecisionLesson,
    FundamentalDriver,
    FundamentalModelVersion,
    ManagementPromise,
    Tenant,
)

BLANK = "      "


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
        tenant = Tenant(external_id="textos-blanco", name="Blank")
        db.add(tenant)
        db.flush()
        ids["tenant"] = tenant.id
        db.info["tenant_id"] = tenant.id
        company = Company(ticker="ACME", name="Acme", exchange="T", currency="USD",
                          company_type="standard", valuation_model="standard_dcf")
        db.add(company)
        db.flush()
        lesson = DecisionLesson(company_id=company.id, taxonomy="thesis_drift",
                                cause="Causa", error="Error", lesson="Lección",
                                future_application="Aplicación", status="proposed")
        promise = ManagementPromise(company_id=company.id, promise="Margen al 30 %",
                                    promise_date=date(2026, 1, 15), expected_period="FY2026",
                                    status="open", evidence=[], metadata_={})
        model = FundamentalModelVersion(
            company_id=company.id, version=1, engine_version="t", algorithm_version="t",
            framework_key="generic_fcf", horizon_years=5, status="ok", publishable=False,
            input_fingerprint="a" * 64, forecast_fingerprint="b" * 64,
            market_snapshot_fingerprint="c" * 64, valuation_snapshot_fingerprint="d" * 64,
        )
        db.add_all([lesson, promise, model])
        db.flush()
        db.add(FundamentalDriver(
            model_version_id=model.id, company_id=company.id, driver_key="revenue",
            driver_type="revenue_driver", required=True, status="sourced",
            value=Decimal("100"), unit="USD", currency="USD", time_basis="per_year",
            period="FY2025", source="filing", confidence=Decimal("0.9"),
        ))
        ids["lesson"], ids["promise"] = lesson.id, promise.id
        db.commit()

    app = FastAPI()
    app.include_router(companies_router, prefix="/api/companies")
    app.include_router(thesis_router, prefix="/api/thesis")

    def _get_db():
        with factory() as s:
            s.info["tenant_id"] = ids["tenant"]
            yield s

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app), ids, factory


def _lesson_body(**extra):
    body = {"taxonomy": "thesis_drift", "cause": "Me fié del guidance",
            "error": "Extrapolé el pico", "lesson": "Normalizar márgenes",
            "future_application": "Usar media de ciclo"}
    body.update(extra)
    return body


@pytest.mark.parametrize("field", ["cause", "error", "lesson", "future_application"])
def test_leccion_con_campo_en_blanco_es_422_y_no_se_guarda(world, field):
    client, ids, factory = world
    resp = client.put(f"/api/companies/ACME/decision-lessons/{ids['lesson']}",
                      json=_lesson_body(**{field: BLANK}))
    assert resp.status_code == 422, resp.text
    with factory() as db:
        db.info["tenant_id"] = ids["tenant"]
        lesson = db.get(DecisionLesson, ids["lesson"])
        assert lesson is not None
        assert getattr(lesson, field).strip()


def test_leccion_valida_se_sigue_guardando(world):
    client, ids, _factory = world
    resp = client.put(f"/api/companies/ACME/decision-lessons/{ids['lesson']}",
                      json=_lesson_body(cause="  Me fié del guidance  "))
    assert resp.status_code == 200, resp.text
    assert resp.json()["cause"] == "Me fié del guidance"


@pytest.mark.parametrize("field", ["promise", "expected_period"])
def test_promesa_en_blanco_es_422(world, field):
    client, _ids, _factory = world
    body = {"promise": "Duplicar el FCF", "promise_date": "2026-03-01",
            "expected_period": "FY2027"}
    body[field] = BLANK
    resp = client.post("/api/companies/ACME/management-credibility/promises", json=body)
    assert resp.status_code == 422, resp.text


def test_promesa_valida_se_sigue_guardando(world):
    client, _ids, _factory = world
    resp = client.post("/api/companies/ACME/management-credibility/promises",
                       json={"promise": "Duplicar el FCF", "promise_date": "2026-03-01",
                             "expected_period": "FY2027"})
    assert resp.status_code == 201, resp.text


def test_explicacion_en_blanco_es_422_y_conserva_la_anterior(world):
    client, ids, factory = world
    url = f"/api/companies/ACME/management-credibility/promises/{ids['promise']}/explanation"
    assert client.put(url, json={"explanation": "Retraso por la planta"}).status_code == 200
    resp = client.put(url, json={"explanation": BLANK})
    assert resp.status_code == 422, resp.text
    with factory() as db:
        db.info["tenant_id"] = ids["tenant"]
        promise = db.get(ManagementPromise, ids["promise"])
        assert promise is not None
        assert promise.management_explanation == "Retraso por la planta"


@pytest.mark.parametrize("field", ["driver_key", "source", "rationale"])
def test_supuesto_de_tesis_en_blanco_es_422(world, field):
    client, _ids, _factory = world
    item = {"driver_key": "revenue", "fiscal_year": 2027, "value": "120",
            "source": "Mi ajuste", "rationale": "Nuevo contrato"}
    item[field] = BLANK
    resp = client.post("/api/thesis/ACME/inputs", json={"inputs": [item]})
    assert resp.status_code == 422, resp.text


def test_supuesto_de_tesis_valido_se_sigue_guardando(world):
    client, _ids, _factory = world
    resp = client.post("/api/thesis/ACME/inputs", json={"inputs": [
        {"driver_key": "revenue", "fiscal_year": 2027, "value": "120",
         "source": "Mi ajuste", "rationale": "Nuevo contrato"}]})
    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize("field", ["driver_key", "source", "rationale"])
def test_version_de_driver_en_blanco_es_422(world, field):
    client, _ids, _factory = world
    body = {"driver_key": "revenue", "fiscal_year": 2027, "value": "120",
            "source": "Mi ajuste", "rationale": "Nuevo contrato"}
    body[field] = BLANK
    resp = client.post("/api/companies/ACME/driver-assumptions", json=body)
    assert resp.status_code == 422, resp.text
