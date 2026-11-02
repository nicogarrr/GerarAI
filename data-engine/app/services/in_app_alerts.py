"""Persistencia idempotente de alertas in-app (ResearchAlert) para watchdogs.

``queue_watchdog`` y ``source_health_watchdog`` llevaban la misma cola de
emisión copiada a mano: dedup por fingerprint (select previo + carrera con
IntegrityError), inserción con savepoint y un único commit al final. Aquí
vive una sola copia; cada watchdog conserva su fingerprint, su mensaje y su
metadata (eso es dominio, no andamio).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ResearchAlert


@dataclass(frozen=True)
class InAppAlert:
    """Una alerta in-app lista para persistir; la construye cada watchdog."""

    fingerprint: str
    alert_type: str
    severity: str
    title: str
    message: str
    metadata: dict[str, Any]


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
        if (
            db.scalar(
                select(ResearchAlert.id).where(
                    ResearchAlert.tenant_id == tenant_id,
                    ResearchAlert.fingerprint == item.fingerprint,
                )
            )
            is not None
        ):
            existing += 1
            continue
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
        try:
            with db.begin_nested():
                db.add(alert)
                db.flush()
        except IntegrityError:
            existing += 1
            continue
        created.append(alert.id)
    db.commit()
    return created, existing
