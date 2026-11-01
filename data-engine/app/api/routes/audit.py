"""Rutas de consulta del registro de auditoria inmutable.

Fulfills: VAL-DB-008
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.audit_service import list_audit_logs

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs", response_model=None)
def get_audit_logs(
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Consulta registros de auditoria inmutables para el tenant activo."""
    logs = list_audit_logs(
        db,
        action=action,
        resource_type=resource_type,
        limit=limit,
        offset=offset,
    )
    return [
        {
            "id": log.id,
            "tenant_id": log.tenant_id,
            "user_id": log.user_id,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "before_state": log.before_state,
            "after_state": log.after_state,
            "ip_address": log.ip_address,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]

