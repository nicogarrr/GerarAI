"""Servicio de registro y consulta de auditoria inmutable.

Fulfills: VAL-DB-008
Expected Behavior:
- Audit log table with user, action, timestamp, before/after state
- Logged operations: portfolio deletion, user role changes, bulk operations
- Append-only tamper-proof audit log
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AuditLog

logger = logging.getLogger(__name__)


def record_audit_event(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    tenant_id: int | None = None,
    user_id: str | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Registra un evento de auditoria inmutable."""
    effective_tenant_id = tenant_id if tenant_id is not None else db.info.get("tenant_id")
    effective_user_id = user_id if user_id is not None else db.info.get("user_id")

    audit_entry = AuditLog(
        tenant_id=effective_tenant_id,
        user_id=effective_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before_state=before_state,
        after_state=after_state,
        ip_address=ip_address,
    )
    db.add(audit_entry)
    logger.info(
        "Auditoria registrada: action=%s resource=%s/%s tenant=%s user=%s",
        action,
        resource_type,
        resource_id,
        effective_tenant_id,
        effective_user_id,
    )
    return audit_entry


def list_audit_logs(
    db: Session,
    *,
    tenant_id: int | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditLog]:
    """Consulta registros de auditoria con filtros opcionales."""
    effective_tenant_id = tenant_id if tenant_id is not None else db.info.get("tenant_id")
    query = select(AuditLog)

    if effective_tenant_id is not None:
        query = query.where(AuditLog.tenant_id == effective_tenant_id)
    if action is not None:
        query = query.where(AuditLog.action == action)
    if resource_type is not None:
        query = query.where(AuditLog.resource_type == resource_type)

    query = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(query).all())

