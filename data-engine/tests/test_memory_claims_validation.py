"""Afirmaciones y pruebas de investigacion (/api/memory).

- ``confidence`` (afirmacion, prueba, seccion de tesis): 1.5 o -3 se guardaban
  como confianza (Numeric(5, 4) los admite) y 50 solo lo paraba Postgres con
  un «fuera de rango» generico. Ahora es 0..1 con 422 que nombra el campo.
- Una afirmacion (o un cambio de tesis) de la empresa A se podia anclar a una
  tesis de la empresa B; al contradecirla, el cambio mezclaba las dos. Ahora 422.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, Tenant
from app.models.entities import ThesisVersion
from tests.auth_helpers import auth_settings, signed_request

SECRET = "memory-claims-validation-test-secret-32ch"


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    suffix = uuid4().hex[:6].upper()
    tenant_ext = f"memclaim-{suffix}"
    with SessionLocal() as db:
        tenant = Tenant(external_id=tenant_ext, name="Memory claims")
        db.add(tenant)
        companies = [
            Company(ticker=f"MC{suffix}{n}", name=f"Empresa {n}", exchange="NASDAQ", currency="USD",
                    sector="Test", industry="Test", company_type="standard",
                    valuation_model="standard_dcf")
            for n in ("A", "B")
        ]
        db.add_all(companies)
        db.commit()
        db.info["tenant_id"] = tenant.id
        thesis_b = ThesisVersion(
            tenant_id=tenant.id, company_id=companies[1].id, version=1, status="draft",
            thesis_markdown="# B", executive_summary="B", rating="watch",
        )
        db.add(thesis_b)
        db.commit()
        ids = {"a": companies[0].id, "b": companies[1].id, "thesis_b": thesis_b.id}
    client = TestClient(main.app)

    def call(method: str, path: str, body=None):
        return signed_request(client, SECRET, tenant_ext, "memclaim-user", method, path, json_body=body)

    return call, ids


def test_confianza_fuera_de_0_1_es_422(env) -> None:
    call, ids = env
    for bad in (50, -3, 1.5):
        res = call("POST", "/api/memory/claims",
                   {"company_id": ids["a"], "statement": "Margen estable", "confidence": bad})
        assert res.status_code == 422, (bad, res.status_code, res.text)
    ok = call("POST", "/api/memory/claims",
              {"company_id": ids["a"], "statement": "Margen estable", "confidence": 0.9})
    assert ok.status_code == 200, ok.text
    claim_id = ok.json()["id"]
    for bad in (12, -0.1):
        res = call("POST", f"/api/memory/claims/{claim_id}/evidence",
                   {"summary": "dato", "confidence": bad})
        assert res.status_code == 422, (bad, res.status_code, res.text)
    good = call("POST", f"/api/memory/claims/{claim_id}/evidence",
                {"summary": "dato", "confidence": 1})
    assert good.status_code == 200, good.text


def test_afirmacion_no_se_ancla_a_la_tesis_de_otra_empresa(env) -> None:
    call, ids = env
    res = call("POST", "/api/memory/claims",
               {"company_id": ids["a"], "thesis_version_id": ids["thesis_b"],
                "statement": "Crece en Europa"})
    assert res.status_code == 422, res.text
    same = call("POST", "/api/memory/claims",
                {"company_id": ids["b"], "thesis_version_id": ids["thesis_b"],
                 "statement": "Crece en Europa"})
    assert same.status_code == 200, same.text
    assert same.json()["thesis_version_id"] == ids["thesis_b"]


def test_cambio_de_tesis_no_mezcla_versiones_de_otra_empresa(env) -> None:
    call, ids = env
    for field in ("from_version_id", "to_version_id"):
        res = call("POST", "/api/memory/thesis/changes",
                   {"company_id": ids["a"], field: ids["thesis_b"], "summary": "Cambio manual"})
        assert res.status_code == 422, (field, res.status_code, res.text)
    ok = call("POST", "/api/memory/thesis/changes",
              {"company_id": ids["b"], "to_version_id": ids["thesis_b"], "summary": "Cambio manual"})
    assert ok.status_code == 200, ok.text


def test_seccion_de_tesis_con_confianza_fuera_de_rango_es_422(env) -> None:
    call, ids = env
    from app.core.database import SessionLocal as _S
    from app.models import Company as _C

    with _S() as db:
        ticker_b = db.get(_C, ids["b"]).ticker
    path = f"/api/memory/thesis/{ticker_b}/versions/{ids['thesis_b']}/sections"
    bad = call("POST", path, {"section_key": "riesgos", "title": "Riesgos", "confidence": 25})
    assert bad.status_code == 422, bad.text
    ok = call("POST", path, {"section_key": "riesgos", "title": "Riesgos", "confidence": 0.6})
    assert ok.status_code == 200, ok.text
