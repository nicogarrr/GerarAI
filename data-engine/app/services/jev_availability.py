"""Estado durable del crédito TypeSafe, compartido por los procesos."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import ResearchAlert, Tenant
from app.models.entities import TypeSafeStatus
from app.services.notification_service import record_in_app_delivery

logger = logging.getLogger(__name__)

# Marcador local del proceso: si no se puede persistir la transición, el
# proceso deja de llamar a TypeSafe y expone el bloqueo operacional.
_PERSISTENCE_BROKEN = False


def credit_status() -> dict:
    if _PERSISTENCE_BROKEN:
        return {"status": "estado_no_disponible", "last_billing_failure_at": None}
    configured = bool(get_settings().typesafe_api_key)
    try:
        with SessionLocal() as db:
            row = db.get(TypeSafeStatus, 1)
            last = row.last_billing_failure_at.isoformat() if row and row.last_billing_failure_at else None
    except Exception:
        # DB sin verificar: no llamar a TypeSafe ni afirmar que está activo.
        return {"status": "estado_no_disponible", "last_billing_failure_at": None}
    return {
        "status": "desactivado_sin_credito" if last else ("activo" if configured else "sin_configurar"),
        "fallback_available": False,
        "last_billing_failure_at": last,
    }


def mark_credit_exhausted() -> None:
    """Primer fallo de facturación. Una alerta de transición por tenant.

    Si dos workers compiten por la fila singleton, el segundo no debe
    emitir otra alerta. Una notificación no compromete la ingesta.
    """
    now = datetime.now(UTC)
    try:
        with SessionLocal() as db:
            row = db.scalar(select(TypeSafeStatus).where(TypeSafeStatus.id == 1).with_for_update())
            if row and row.last_billing_failure_at:
                return
            if row is None:
                row = TypeSafeStatus(id=1, last_billing_failure_at=now)
                db.add(row)
            else:
                row.last_billing_failure_at = now
            db.flush()
            tenant_ids = list(
                db.scalars(select(Tenant.id).where(Tenant.status == "active"))
            )
            db.commit()
    except Exception:  # noqa: BLE001
        global _PERSISTENCE_BROKEN
        _PERSISTENCE_BROKEN = True
        logger.exception(
            "Cannot persist TypeSafe billing transition; "
            "process stops TypeSafe calls and reports estado_no_disponible"
        )
        return
    for tenant_id in tenant_ids:
        # Las alertas son filas tenant-owned: con research_auth_required los
        # guards de database.py rechazan escrituras tenant-owned en sesiones
        # sin contexto (RuntimeError «Tenant context is required for
        # tenant-owned writes»). Cada alerta se escribe en una sesión con el
        # contexto de su tenant, y un fallo puntual no compromete la ingesta.
        try:
            with SessionLocal() as tenant_db:
                tenant_db.info["tenant_id"] = tenant_id
                alert = ResearchAlert(
                    tenant_id=tenant_id, alert_type="typesafe_credit_exhausted",
                    severity="medium", status="open", title="Crédito de TypeSafe agotado",
                    message="JEV está desactivado por falta de crédito; se conserva toda la evidencia sin etiquetas alternativas.",
                    fingerprint=f"typesafe_credit_exhausted:{tenant_id}",
                    channels=["in_app"], metadata_={"changed_at": now.isoformat(), "audience": "internal_ops"},
                )
                tenant_db.add(alert)
                tenant_db.flush()
                record_in_app_delivery(tenant_db, alert)
                tenant_db.commit()
        except Exception:  # noqa: BLE001
            logger.exception(
                "Cannot persist TypeSafe credit alert for tenant %s", tenant_id
            )
