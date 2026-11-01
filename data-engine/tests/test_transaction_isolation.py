"""Pruebas de nivel de aislamiento transaccional y unicidad de cartera (VAL-DB-007).

Fulfills: VAL-DB-007
Expected Behavior:
- READ COMMITTED isolation level configured on PostgreSQL
- Multi-step operations wrapped in database transactions
- Rollback on any step failure (no partial commits)
- Creating duplicate portfolio name for same user returns 409 Conflict
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import portfolio as portfolio_routes
from app.core.database import _engine_isolation_kwargs, get_db
from app.models.entities import Base, Company, Tenant, Transaction


@pytest.fixture
def env():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    with factory() as s:
        t = Tenant(external_id="tenant-iso-1", name="t", metadata_={})
        s.add(t)
        s.commit()
        tid = t.id

    def _db():
        with factory() as session:
            session.info["tenant_id"] = tid
            yield session

    app = FastAPI()
    app.include_router(portfolio_routes.router, prefix="/api/portfolio")
    app.dependency_overrides[get_db] = _db
    yield TestClient(app, raise_server_exceptions=False), factory


def test_engine_isolation_kwargs_postgres():
    """Verifica que PostgreSQL configure explicitamente READ COMMITTED."""
    pg_kwargs = _engine_isolation_kwargs("postgresql://user:pass@localhost:5432/gerarai")
    assert pg_kwargs == {"isolation_level": "READ COMMITTED"}

    pg_plus_kwargs = _engine_isolation_kwargs("postgresql+psycopg2://user:pass@localhost/db")
    assert pg_plus_kwargs == {"isolation_level": "READ COMMITTED"}

    sqlite_kwargs = _engine_isolation_kwargs("sqlite:///:memory:")
    assert sqlite_kwargs == {}


def test_create_portfolio_success_and_conflict(env):
    """VAL-DB-007: Creacion de cartera y 409 Conflict ante duplicados por usuario."""
    client, _ = env

    # 1. Crear cartera inicial
    res1 = client.post(
        "/api/portfolio",
        json={"name": "Cartera Dividendos", "base_currency": "EUR"},
    )
    assert res1.status_code == 201, res1.text
    data1 = res1.json()
    assert data1["name"] == "Cartera Dividendos"
    assert data1["base_currency"] == "EUR"
    assert data1["is_default"] is False
    assert "id" in data1

    # 2. Intentar crear duplicado con el mismo nombre -> 409 Conflict
    res2 = client.post(
        "/api/portfolio",
        json={"name": "Cartera Dividendos", "base_currency": "EUR"},
    )
    assert res2.status_code == 409, res2.text
    assert "Ya existe una cartera con este nombre" in res2.json()["detail"]

    # 3. Listar carteras
    res_list = client.get("/api/portfolio")
    assert res_list.status_code == 200
    names = [p["name"] for p in res_list.json()]
    assert "Cartera Dividendos" in names


def test_batch_transaction_atomic_rollback_on_failure(env):
    """Verifica que una operacion por lotes multi-paso haga rollback total ante error."""
    client, factory = env

    with factory() as s:
        company = Company(
            ticker="SAP",
            name="SAP SE",
            exchange="XETRA",
            currency="EUR",
            company_type="operating",
            valuation_model="standard",
        )
        s.add(company)
        s.commit()

    # Pre-condicion: 0 transacciones
    with factory() as s:
        tx_count_before = len(list(s.scalars(select(Transaction)).all()))
        assert tx_count_before == 0

    # Lote donde el 1er elemento es valido pero el 2do es invalido (oversell: venta de 50 cuando solo se compran 10)
    batch_payload = {
        "transactions": [
            {
                "ticker": "SAP",
                "action": "buy",
                "quantity": 10.0,
                "price": 150.0,
                "fees": 2.0,
                "currency": "EUR",
                "trade_date": "2026-03-01",
            },
            {
                "ticker": "SAP",
                "action": "sell",
                "quantity": 50.0,  # Intento de sobreventa (oversell)
                "price": 160.0,
                "fees": 2.0,
                "currency": "EUR",
                "trade_date": "2026-03-02",
            },
        ]
    }

    res = client.post(
        "/api/portfolio/transactions/batch",
        json=batch_payload,
    )
    assert res.status_code in {400, 409, 422}, res.text
    assert "Cannot sell" in res.json()["detail"]

    # Atomicidad: el 1er elemento NO debe haberse persistido
    with factory() as s:
        tx_count_after = len(list(s.scalars(select(Transaction)).all()))
        assert tx_count_after == 0, "No debe haber registros parciales tras fallo de lote"
