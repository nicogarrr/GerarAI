"""GET /api/alerts/rules con filas legacy malformadas no debe tumbar el listado.

Una sola regla con un campo JSON con forma antigua (p. ej. ``last_result`` o
``metadata`` como string, o ``channels`` como string suelto) hace fallar la
validacion del response_model y devuelve 500 para TODAS las alertas de la
cuenta, con mensaje persistente en el frontend. El listado debe ser robusto:
campos JSON tolerantes a formas legacy.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models.entities import AlertRule, Company, Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "legacy-rows-secret"


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

    return call, suffix


def _seed_legacy_rule(call, suffix) -> int:
    call("a", "GET", "/api/alerts/rules")
    with SessionLocal() as db:
        tenant = db.scalar(
            select(Tenant).where(Tenant.external_id == f"a-{suffix}")
        )
        company = Company(
            ticker=f"LG{suffix[:4].upper()}", name="Legacy Co", exchange="NASDAQ", currency="USD",
            sector="Tech", industry="Software", company_type="standard",
            valuation_model="standard_dcf", special_sources=[], special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        db.flush()
        rule = AlertRule(
            tenant_id=tenant.id,
            company_id=company.id,
            name="legacy rule",
            rule_type="price_above",
            condition={"value": 100},
            target={},
            severity="medium",
            channels=["in_app"],
            active=True,
            cooldown_seconds=3600,
            trigger_count=0,
            last_result={},
            metadata_={"ticker": company.ticker, "source": "user"},
        )
        db.add(rule)
        db.commit()
        rule_id = rule.id
        # Formas legacy que PostgreSQL json/jsonb admite pero el esquema no:
        # last_result/metadata como string y channels como string suelto.
        db.execute(
            text(
                "UPDATE alert_rules SET last_result = :legacy_str, "
                "metadata = :legacy_str, channels = :channels_str "
                "WHERE id = :rule_id"
            ),
            {"rule_id": rule_id, "legacy_str": "\"legacy\"", "channels_str": "\"in_app\""},
        )
        db.commit()
    return rule_id


def test_one_legacy_row_does_not_500_the_whole_rules_list(world):
    call, suffix = world
    rule_id = _seed_legacy_rule(call, suffix)
    res = call("a", "GET", "/api/alerts/rules", params={"active": "true"})
    assert res.status_code == 200, res.text
    items = res.json()
    rule = next(r for r in items if r["id"] == rule_id)
    assert rule["last_result"] == {}
    assert rule["metadata"] == {}
    assert rule["channels"] == ["in_app"]
