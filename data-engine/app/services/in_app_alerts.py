"""Persistencia idempotente de alertas in-app (ResearchAlert) para watchdogs.

``queue_watchdog`` y ``source_health_watchdog`` llevaban la misma cola de
emisión copiada a mano: dedup por fingerprint (select previo + carrera con
IntegrityError), inserción con savepoint y un único commit al final. Aquí
vive una sola copia; cada watchdog conserva su fingerprint, su mensaje y su
metadata (eso es dominio, no andamio).

``insert_alert_once`` es la primitiva compartida de esa cola; también la usa
``macro_reminders`` (misma dedup por fingerprint sobre ResearchAlert).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ResearchAlert
from app.services.notification_service import record_in_app_delivery


@dataclass(frozen=True)
class InAppAlert:
    """Una alerta in-app lista para persistir; la construye cada watchdog."""

    fingerprint: str
    alert_type: str
    severity: str
    title: str
    message: str
    metadata: dict[str, Any]


def insert_alert_once(db: Session, alert: ResearchAlert) -> bool:
    """Graba ``alert`` si no hay ya una fila con su (tenant, fingerprint).

    Devuelve ``True`` si la fila es nueva. Idempotente: dedup por
    fingerprint (select previo, o IntegrityError si otra corrida gana la
    carrera, bajo savepoint). No commitea: el caller hace un único commit
    al final de su lote (un rollback no consume transiciones).
    """
    if (
        db.scalar(
            select(ResearchAlert.id).where(
                ResearchAlert.tenant_id == alert.tenant_id,
                ResearchAlert.fingerprint == alert.fingerprint,
            )
        )
        is not None
    ):
        return False
    try:
        with db.begin_nested():
            db.add(alert)
            db.flush()
    except IntegrityError:
        return False
    # La alerta in_app esta entregada en cuanto existe: sin la fila de
    # entrega, la UI la muestra "sin registro de entrega" para siempre
    # (observado en prod el 09-nov-2026: "Cola yahoo atascada ... sin
    # registro de entrega" mientras las de noticias salian "entregada").
    # record_in_app_delivery es idempotente y no commitea.
    record_in_app_delivery(db, alert)
    return True


def persist_in_app_alerts(
    db: Session,
    *,
    tenant_id: Any,
    now: datetime,
    alerts: list[InAppAlert],
) -> tuple[list[int], int]:
    """Persiste cada alerta una sola vez por fingerprint.

    Devuelve ``(ids_creados, ya_existentes)``. Idempotente: si la fila ya
    existe (select previo, o IntegrityError si otra corrida gana la carrera)
    cuenta como existente y se sigue con la siguiente. Un único commit al
    final: el caller graba sus marcas de "ya visto" DESPUÉS de que esta
    función vuelva (un rollback no consume transiciones).
    """
    created: list[int] = []
    existing = 0
    for item in alerts:
        alert = ResearchAlert(
            tenant_id=tenant_id,
            company_id=None,
            severity=item.severity,
            status="open",
            alert_type=item.alert_type,
            title=item.title,
            message=item.message,
            fingerprint=item.fingerprint,
            channels=["in_app"],
            last_triggered_at=now,
            metadata_=item.metadata,
        )
        if insert_alert_once(db, alert):
            created.append(alert.id)
        else:
            existing += 1
    db.commit()
    return created, existing
