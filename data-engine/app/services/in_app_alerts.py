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


def _ensure_in_app_delivery(db: Session, *, tenant_id: Any, fingerprint: str) -> None:
    """Backfill perezoso: registra la entrega in_app de una alerta ya persistida.

    Las alertas de los watchdogs creadas antes de que insert_alert_once
    registrara la entrega (09-nov-2026) quedaron marcadas en la UI "sin
    registro de entrega" aunque estan en la app. Al reencontrarlas por dedup
    (un tick por ciclo) se graba la entrega de la fila existente: idempotente
    (record_in_app_delivery dedup por alerta+canal), sin script ops y sin
    tocar nada que no pase por esta funcion (solo la usan los watchdogs).
    Si la carrera de IntegrityError aun no es visible, el siguiente tick lo
    recoge.
    """
    existing_alert = db.scalar(
        select(ResearchAlert).where(
            ResearchAlert.tenant_id == tenant_id,
            ResearchAlert.fingerprint == fingerprint,
        )
    )
    if existing_alert is not None:
        record_in_app_delivery(db, existing_alert)


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
            _ensure_in_app_delivery(db, tenant_id=tenant_id, fingerprint=item.fingerprint)
    db.commit()
    return created, existing
