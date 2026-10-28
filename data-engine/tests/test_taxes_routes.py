"""Rutas /taxes: validación de ejercicio, errores mapeados a HTTP y que la vista
previa y el GET no escriban datos. Esquema propio en memoria.

Run from data-engine/:
    pytest tests/test_taxes_routes.py -v
"""

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import taxes
from app.core.database import Base, get_db
from app.models import TaxReport, Tenant


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        t = Tenant(external_id="tax-routes", name="t", metadata_={})
        s.add(t)
        s.commit()
        tenant_id = t.id

    def _db():
        with factory() as session:
            session.info["tenant_id"] = tenant_id
            yield session

    app = FastAPI()
    app.include_router(taxes.router, prefix="/taxes")
    app.dependency_overrides[get_db] = _db
    yield TestClient(app, raise_server_exceptions=False), factory


@pytest.mark.parametrize("year", [1999, 2201])
@pytest.mark.parametrize("method,path", [
    ("get", "/taxes/report/{y}"),
    ("post", "/taxes/report/{y}/regenerate"),
    ("get", "/taxes/modelo720/{y}/thresholds"),
    ("get", "/taxes/modelo720/{y}/file"),
])
def test_year_out_of_range_is_400_everywhere(env, method, path, year):
    client, _ = env
    r = getattr(client, method)(path.format(y=year))
    assert r.status_code == 400
    assert "2000" in r.json()["detail"]


def test_preview_rejects_tme_outside_0_100_and_extra_decimals(env):
    client, _ = env
    for bad in (-1, 100.01, "19.123"):
        r = client.post("/taxes/report/2024/preview", json={"tme_percent": bad})
        assert r.status_code == 422, bad
    assert client.post("/taxes/report/2024/preview", json={}).status_code == 422
    assert client.post("/taxes/report/1990/preview", json={"tme_percent": 19}).status_code == 400


def test_preview_converts_percent_to_ratio_and_maps_value_error(env, monkeypatch):
    client, _ = env
    seen = {}

    class Fake:
        def get_report(self, db, year, tme=None):
            seen["tme"], seen["year"] = tme, year
            return {"ok": True}

    monkeypatch.setattr(taxes, "TaxReportService", Fake)
    r = client.post("/taxes/report/2024/preview", json={"tme_percent": "19.00"})
    assert r.status_code == 200 and seen == {"tme": Decimal("0.19"), "year": 2024}

    class Boom:
        def get_report(self, *a, **k):
            raise ValueError("sin datos")

    monkeypatch.setattr(taxes, "TaxReportService", Boom)
    r = client.post("/taxes/report/2024/preview", json={"tme_percent": 5})
    assert r.status_code == 400 and r.json()["detail"] == "sin datos"
    r = client.get("/taxes/report/2024")
    assert r.status_code == 400 and r.json()["detail"] == "sin datos"

    class BoomRegen:
        def regenerate_report(self, *a, **k):
            raise ValueError("no regenerable")

    monkeypatch.setattr(taxes, "TaxReportService", BoomRegen)
    r = client.post("/taxes/report/2024/regenerate")
    assert r.status_code == 400 and r.json()["detail"] == "no regenerable"


def test_get_report_and_preview_do_not_persist(env):
    client, factory = env
    assert client.get("/taxes/report/2024").status_code in (200, 400)
    assert client.post("/taxes/report/2024/preview", json={"tme_percent": 19}).status_code in (200, 400)
    with factory() as s:
        assert s.query(TaxReport).count() == 0


def test_declarant_roundtrip_and_error_mapping(env, monkeypatch):
    client, _ = env
    assert client.put("/taxes/declarant", json={"nif": "12345678Z", "bogus": 1}).status_code == 422
    r = client.put("/taxes/declarant", json={"nif": "12345678Z", "apellidos_nombre": "Perez Ana"})
    assert r.status_code == 200
    got = client.get("/taxes/declarant").json()
    assert got["nif"] == "12345678Z"

    def deny(*a, **k):
        raise PermissionError("sin acceso")

    monkeypatch.setattr(taxes.tax_declarant_service, "read", deny)
    monkeypatch.setattr(taxes.tax_declarant_service, "write", deny)
    assert client.get("/taxes/declarant").status_code == 403
    assert client.put("/taxes/declarant", json={"nif": "x"}).status_code == 403

    def bad(*a, **k):
        raise ValueError("NIF inválido")

    monkeypatch.setattr(taxes.tax_declarant_service, "write", bad)
    r = client.put("/taxes/declarant", json={"nif": "x"})
    assert r.status_code == 400 and r.json()["detail"] == "NIF inválido"


def test_holdings_and_modelo720_endpoints_respond(env):
    client, _ = env
    assert client.get("/taxes/holdings").json() == []
    r = client.get("/taxes/modelo720/2024/file")
    assert r.status_code == 200 and r.json().get("available") is False
    assert client.get("/taxes/modelo720/2024/thresholds").status_code == 200
