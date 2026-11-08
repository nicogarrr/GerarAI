"""Ruta GET /audit/logs (app/api/routes/audit.py): serializacion, aislamiento
por tenant, filtros/paginacion y created_at nulo."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.audit import get_audit_logs
from app.models.entities import AuditLog, Base
from app.services.audit_service import record_audit_event


def _db() -> Session:
    db = Session(create_engine("sqlite://"))
    Base.metadata.create_all(db.get_bind())
    db.info["tenant_id"] = 1
    return db


def test_serializa_solo_registros_del_tenant():
    db = _db()
    record_audit_event(
        db,
        action="delete",
        resource_type="portfolio",
        resource_id="7",
        user_id="u1",
        before_state={"name": "vieja"},
        after_state=None,
        ip_address="1.2.3.4",
    )
    db.add(AuditLog(tenant_id=2, action="delete", resource_type="portfolio"))
    db.commit()
    out = get_audit_logs(action=None, resource_type=None, limit=50, offset=0, db=db)
    assert len(out) == 1
    row = out[0]
    assert row["tenant_id"] == 1
    assert row["user_id"] == "u1"
    assert row["action"] == "delete"
    assert row["resource_type"] == "portfolio"
    assert row["resource_id"] == "7"
    assert row["before_state"] == {"name": "vieja"}
    assert row["after_state"] is None
    assert row["ip_address"] == "1.2.3.4"
    assert "T" in row["created_at"]


def test_filtros_y_paginacion():
    db = _db()
    for action in ("create", "create", "delete"):
        record_audit_event(db, action=action, resource_type="portfolio")
    db.commit()
    assert len(get_audit_logs(action="delete", resource_type=None, limit=50, offset=0, db=db)) == 1
    assert len(get_audit_logs(action=None, resource_type="portfolio", limit=50, offset=0, db=db)) == 3
    assert len(get_audit_logs(action=None, resource_type="otro", limit=50, offset=0, db=db)) == 0
    assert len(get_audit_logs(action=None, resource_type=None, limit=1, offset=1, db=db)) == 1


def test_created_at_nulo_se_serializa_como_none(monkeypatch):
    pendiente = AuditLog(id=5, tenant_id=1, user_id=None, action="x", resource_type="y")
    monkeypatch.setattr("app.api.routes.audit.list_audit_logs", lambda *a, **k: [pendiente])
    out = get_audit_logs(action=None, resource_type=None, limit=50, offset=0, db=_db())
    assert out[0]["created_at"] is None
