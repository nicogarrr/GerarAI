"""Detalle del run: el ultimo precio por empresa se lee con row_number.

Antes se traia TODO el historico de barras de cada candidata para
quedarse con la ultima fila; la consulta numerada lee una fila por
empresa y mantiene el mismo current_price/price_as_of (None honesto).
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, engine, init_db
from app.models import MarketPrice, Tenant
from tests.auth_helpers import auth_settings, signed_request
from tests.test_propicks_api import SECRET, _seed_company


@pytest.fixture
def required_auth(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )


def test_run_detail_reads_one_price_row_per_company(required_auth):
    init_db()
    suffix = uuid4().hex[:8]
    tenant_ext = f"propicks-rn-{suffix}"
    db = SessionLocal()
    tenant = Tenant(external_id=tenant_ext, name="ProPicks rn test")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    company = _seed_company(db, tenant.id, f"ROWN{suffix[:4]}", "0.20", "0.16")
    recent = date(2026, 10, 20)
    # 400 barras viejas y la ultima: solo esta puede salir como current_price.
    for back in range(1, 401):
        db.add(MarketPrice(company_id=company.id, date=recent - timedelta(days=back),
                           close=Decimal("9999"), volume=1000))
    db.add(MarketPrice(company_id=company.id, date=recent, close=Decimal("42"), volume=1000))
    db.commit()
    company_id = company.id
    db.close()

    client = TestClient(main.app)
    created = signed_request(client, SECRET, tenant_ext, "propicks-rn-user", "POST", "/api/propicks/runs")
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    statements = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        if "FROM market_prices" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        detail = signed_request(client, SECRET, tenant_ext, "propicks-rn-user", "GET", f"/api/propicks/runs/{run_id}")
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert detail.status_code == 200
    by_company = {c["company_id"]: c for c in detail.json()["candidates"]}
    assert by_company[company_id]["current_price"] == 42.0
    assert by_company[company_id]["price_as_of"] == recent.isoformat()
    assert statements, "se esperaba la consulta de precios"
    assert any("row_number" in stmt.lower() for stmt in statements), \
        "la consulta de precios debe numerar por empresa, no ordenar el historico"
