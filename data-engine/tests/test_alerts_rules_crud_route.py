"""Contrato HTTP del CRUD de reglas de alerta: POST /api/alerts y DELETE
/api/alerts/rules/{id} con auth real (firma ligada), servicio real, sin mock.

GET /rules ya tiene cobertura HTTP (test_alerts_rules_legacy_rows); el alta y
la baja solo se ejercitaban a nivel de servicio/handler directo.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models.entities import AlertRule, Company
from tests.auth_helpers import auth_settings, signed_request

SECRET = "alerts-rules-crud-secret"


@pytest.fixture()
def world(monkeypatch):
    init_db()
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET, app_env="test"),
    )
    suffix = uuid4().hex[:8]
    client = TestClient(main.app, raise_server_exceptions=False)

    def call(tenant, method, path, json_body=None, params=None):
        return signed_request(
            client, SECRET, f"{tenant}-{suffix}", f"user-{tenant}-{suffix}",
            method, path, json_body=json_body, params=params,
        )

    ticker = f"CR{suffix[:4].upper()}"
    with SessionLocal() as db:
        db.add(Company(
            ticker=ticker, name="Crud Co", exchange="NASDAQ", currency="USD",
            sector="Tech", industry="Software", company_type="standard",
            valuation_model="standard_dcf", special_sources=[], special_risks=[],
            factor_tags=[],
        ))
        db.commit()
    return call, suffix, ticker


def test_crear_regla_201_contrato_alertruleout(world):
    call, suffix, ticker = world
    res = call("a", "POST", "/api/alerts", json_body={
        "ticker": ticker, "alert_type": "price_above", "operator": ">", "value": 150,
    })
    assert res.status_code == 201, res.text
    payload = res.json()
    assert payload["rule_type"] == "price_above"
    assert payload["active"] is True
    assert payload["condition"]["value"] == 150
    assert payload["trigger_count"] == 0
    # Aparece en el listado del tenant.
    rules = call("a", "GET", "/api/alerts/rules").json()
    assert [r["id"] for r in rules] == [payload["id"]]


def test_crear_regla_ticker_desconocido_404(world):
    call, suffix, ticker = world
    res = call("a", "POST", "/api/alerts", json_body={
        "ticker": f"NOPE{suffix[:4].upper()}", "alert_type": "price_above",
        "operator": ">", "value": 150,
    })
    assert res.status_code == 404


def test_crear_regla_sin_firma_403(world):
    call, suffix, ticker = world
    client = TestClient(main.app, raise_server_exceptions=False)
    res = client.post("/api/alerts", json={
        "ticker": ticker, "alert_type": "price_above", "operator": ">", "value": 150,
    })
    assert res.status_code == 403
    with SessionLocal() as db:
        # Ninguna regla creada para el ticker de esta prueba.
        assert db.scalars(
            select(AlertRule).join(Company, AlertRule.company_id == Company.id).where(
                Company.ticker == ticker
            )
        ).all() == []


def test_borrar_regla_la_desactiva(world):
    call, suffix, ticker = world
    rule_id = call("a", "POST", "/api/alerts", json_body={
        "ticker": ticker, "alert_type": "price_below", "operator": "<", "value": 90,
    }).json()["id"]

    res = call("a", "DELETE", f"/api/alerts/rules/{rule_id}")
    assert res.status_code == 200, res.text
    assert res.json()["active"] is False
    activas = call("a", "GET", "/api/alerts/rules", params={"active": "true"}).json()
    assert [r["id"] for r in activas] == []
    inactivas = call("a", "GET", "/api/alerts/rules", params={"active": "false"}).json()
    assert [r["id"] for r in inactivas] == [rule_id]


def test_borrar_regla_inexistente_404(world):
    call, suffix, ticker = world
    assert call("a", "DELETE", "/api/alerts/rules/99999999").status_code == 404


def test_borrar_regla_de_otro_tenant_404(world):
    call, suffix, ticker = world
    rule_id = call("a", "POST", "/api/alerts", json_body={
        "ticker": ticker, "alert_type": "price_above", "operator": ">", "value": 150,
    }).json()["id"]

    assert call("b", "DELETE", f"/api/alerts/rules/{rule_id}").status_code == 404
    # Sigue activa para su dueno.
    activas = call("a", "GET", "/api/alerts/rules", params={"active": "true"}).json()
    assert [r["id"] for r in activas] == [rule_id]
