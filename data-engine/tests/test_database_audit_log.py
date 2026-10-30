"""Pruebas del registro de auditoria inmutable (AuditLog) y proteccion append-only.

Fulfills: VAL-DB-008
Expected Behavior:
- Audit log table with user, action, timestamp, before/after state
- Logged operations: portfolio creation, sensitive changes
- Audit log queryable via API/admin interface
- Tamper-proof audit log (append-only: update/delete rejected)
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import audit as audit_routes
from app.api.routes import portfolio as portfolio_routes
from app.core.database import Base, get_db
from app.models.entities import AuditLog, Tenant
from app.services.audit_service import list_audit_logs, record_audit_event


@pytest.fixture
def env():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    with factory() as s:
        t = Tenant(external_id="tenant-audit-test", name="Tenant Audit", metadata_={})
        s.add(t)
        s.commit()
        tid = t.id

    def _db():
        with factory() as session:
            session.info["tenant_id"] = tid
            session.info["user_id"] = "user_test_audit_42"
            yield session

    app = FastAPI()
    app.include_router(audit_routes.router, prefix="/api")
    app.include_router(portfolio_routes.router, prefix="/api/portfolio")
    app.dependency_overrides[get_db] = _db
    yield TestClient(app, raise_server_exceptions=False), factory


def test_record_audit_event_and_query(env):
    """Verifica que record_audit_event persista correctamente y list_audit_logs filtre por accion."""
    _, factory = env

    with factory() as s:
        s.info["tenant_id"] = 10
        s.info["user_id"] = "user_admin_1"

        entry1 = record_audit_event(
            s,
            action="portfolio_deleted",
            resource_type="portfolio",
            resource_id="101",
            before_state={"name": "Cartera Vieja", "positions_count": 3},
            after_state=None,
        )
        entry2 = record_audit_event(
            s,
            action="role_changed",
            resource_type="user",
            resource_id="user_admin_2",
            before_state={"role": "member"},
            after_state={"role": "admin"},
        )
        s.commit()

        assert entry1.id is not None
        assert entry2.id is not None

        # Consultar por accion especifica
        logs_deleted = list_audit_logs(s, tenant_id=10, action="portfolio_deleted")
        assert len(logs_deleted) == 1
        assert logs_deleted[0].resource_id == "101"
        assert logs_deleted[0].before_state == {"name": "Cartera Vieja", "positions_count": 3}

        # Consultar todos para el tenant
        all_logs = list_audit_logs(s, tenant_id=10)
        assert len(all_logs) == 2


def test_audit_log_append_only_tamper_proof(env):
    """Verifica que AuditLog sea append-only y rechace cualquier UPDATE o DELETE."""
    _, factory = env

    with factory() as s:
        s.info["tenant_id"] = 10
        entry = record_audit_event(
            s,
            action="security_policy_updated",
            resource_type="system",
            after_state={"mfa_required": True},
        )
        s.commit()
        entry_id = entry.id

    # 1. Intento de UPDATE
    with factory() as s:
        target = s.get(AuditLog, entry_id)
        assert target is not None
        target.action = "tampered_action"
        with pytest.raises(RuntimeError, match="AuditLog is append-only and cannot be updated or deleted"):
            s.flush()
        s.rollback()

    # 2. Intento de DELETE
    with factory() as s:
        target = s.get(AuditLog, entry_id)
        assert target is not None
        s.delete(target)
        with pytest.raises(RuntimeError, match="AuditLog is append-only and cannot be updated or deleted"):
            s.flush()
        s.rollback()


def test_api_audit_logs_endpoint_integration(env):
    """Verifica que las operaciones de API registren auditoria consultable via endpoint."""
    client, _ = env

    # Crear una cartera via API
    res_create = client.post(
        "/api/portfolio",
        json={"name": "Cartera Auditada", "base_currency": "EUR"},
    )
    assert res_create.status_code == 201, res_create.text

    # Consultar endpoint de auditoria
    res_audit = client.get("/api/audit/logs")
    assert res_audit.status_code == 200, res_audit.text
    logs = res_audit.json()
    assert len(logs) >= 1

    matching = [log for log in logs if log["action"] == "portfolio_created"]
    assert len(matching) == 1
    assert matching[0]["resource_type"] == "portfolio"
    assert matching[0]["after_state"]["name"] == "Cartera Auditada"

