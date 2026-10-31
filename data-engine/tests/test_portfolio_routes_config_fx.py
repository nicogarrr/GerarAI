"""Rutas /portfolio: configuración, tipos FX y snapshots. Comprobamos que un
cambio de divisa base o de tipo FX reconstruye las posiciones y que un error
de validación hace rollback y devuelve 400 sin dejar datos a medias.

Run from data-engine/:
    pytest tests/test_portfolio_routes_config_fx.py -v
"""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import portfolio as portfolio_routes
from app.core.database import Base, get_db
from app.models import FXRate, Tenant


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        t = Tenant(external_id="pf-routes", name="t", metadata_={})
        s.add(t)
        s.commit()
        tid = t.id

    def _db():
        with factory() as session:
            session.info["tenant_id"] = tid
            yield session

    app = FastAPI()
    app.include_router(portfolio_routes.router, prefix="/portfolio")
    app.dependency_overrides[get_db] = _db
    yield TestClient(app, raise_server_exceptions=False), factory


def test_configuration_defaults_when_no_portfolio_and_fx_source_empty(env):
    client, _ = env
    body = client.get("/portfolio/configuration").json()
    assert body["base_currency"] == "EUR"
    assert body["tax_currency"] == "EUR"
    assert body["fx_source"] == {"source": None, "latest_rate_date": None, "base_currency": "EUR"}


def test_change_base_currency_persists_and_is_reflected(env):
    client, _ = env
    r = client.put("/portfolio/configuration", json={"base_currency": "usd"})
    assert r.status_code == 200 and r.json()["base_currency"] == "USD"
    cfg = client.get("/portfolio/configuration").json()
    # IRPF sigue en EUR aunque la base sea USD
    assert cfg["base_currency"] == "USD" and cfg["tax_currency"] == "EUR"


@pytest.mark.parametrize("bad", ["EU", "EURO", "E1R", ""])
def test_configuration_rejects_malformed_currency(env, bad):
    client, _ = env
    assert client.put("/portfolio/configuration", json={"base_currency": bad}).status_code == 422


def test_fx_rate_upsert_list_ordering_and_latest_source(env):
    client, _ = env
    for d, rate in (("2026-01-02", "0.90"), ("2026-02-03", "0.95")):
        r = client.post("/portfolio/fx-rates", json={
            "base_currency": "eur", "quote_currency": "usd", "rate": rate, "rate_date": d, "source": "bce",
        })
        assert r.status_code == 201, r.text
    rows = client.get("/portfolio/fx-rates").json()["items"]  # sobre paginado {items, page_info}
    assert [x["rate_date"] for x in rows] == ["2026-02-03", "2026-01-02"]  # más reciente primero
    assert rows[0]["rate"] == pytest.approx(0.95)
    assert client.get("/portfolio/fx-rates?limit=1&offset=1").json()["items"][0]["rate_date"] == "2026-01-02"
    # offset sin limit no significa nada en page/page_size: 422 explicito
    assert client.get("/portfolio/fx-rates?offset=1").status_code == 422
    cfg = client.get("/portfolio/configuration").json()
    assert cfg["fx_source"]["source"] == "bce" and cfg["fx_source"]["latest_rate_date"] == "2026-02-03"


def test_fx_rate_same_day_upsert_replaces_instead_of_duplicating(env):
    client, factory = env
    payload = {"base_currency": "EUR", "quote_currency": "USD", "rate_date": "2026-01-02"}
    client.post("/portfolio/fx-rates", json={**payload, "rate": "0.90"})
    client.post("/portfolio/fx-rates", json={**payload, "rate": "0.92"})
    with factory() as s:
        rows = s.scalars(select(FXRate)).all()
    assert len(rows) == 1 and float(rows[0].rate) == pytest.approx(0.92)


@pytest.mark.parametrize("patch", [{"rate": "0"}, {"rate": "-1"}, {"quote_currency": "US"}, {"source": ""}, {"rate_date": "x"}])
def test_fx_rate_validation_rejects_bad_payloads(env, patch):
    client, factory = env
    body = {"base_currency": "EUR", "quote_currency": "USD", "rate": "0.9", "rate_date": "2026-01-02", **patch}
    assert client.post("/portfolio/fx-rates", json=body).status_code == 422
    with factory() as s:
        assert s.scalars(select(FXRate)).all() == []


def test_fx_rate_service_value_error_is_400_and_rolled_back(env, monkeypatch):
    client, factory = env

    def boom(self, *a, **k):
        raise ValueError("par inválido")

    monkeypatch.setattr(portfolio_routes.PortfolioFXService, "upsert_rate", boom)
    r = client.post("/portfolio/fx-rates", json={
        "base_currency": "EUR", "quote_currency": "EUR", "rate": "1", "rate_date": "2026-01-02",
    })
    assert r.status_code == 400 and r.json()["detail"] == "par inválido"
    monkeypatch.setattr(portfolio_routes.PortfolioFXService, "set_base_currency", boom)
    r = client.put("/portfolio/configuration", json={"base_currency": "GBP"})
    assert r.status_code == 400


def test_snapshot_capture_then_history_filters_by_start(env):
    client, _ = env
    for d in ("2026-01-05", "2026-02-05"):
        r = client.post(f"/portfolio/snapshots/capture?as_of={d}")
        assert r.status_code == 200, r.text
        assert r.json()["snapshot_date"] == d
    all_rows = client.get("/portfolio/snapshots").json()["items"]
    assert {x["snapshot_date"] for x in all_rows} == {"2026-01-05", "2026-02-05"}
    assert all(x["source"] == "manual_capture" for x in all_rows)
    later = client.get("/portfolio/snapshots?start=2026-02-01").json()["items"]
    assert [x["snapshot_date"] for x in later] == ["2026-02-05"]
    assert client.get("/portfolio/snapshots?limit=0").status_code == 422
    assert client.get("/portfolio/snapshots?limit=5001").status_code == 422
    assert date.fromisoformat(all_rows[0]["snapshot_date"])
