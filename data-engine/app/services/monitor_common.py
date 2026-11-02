"""Nucleo compartido de los monitores programados contra SEC EDGAR.

``schedule13dg_monitor`` nacio como espejo de ``insider_monitor`` (PR-3) y el
esqueleto comun ya se habia desalineado a mano: el handler de fallo fatal del
13D/G llevaba el rollback + relectura del estado (una sesion envenenada no
acepta commit) y el insider no. Aqui vive una sola copia — espejo por
construccion — del watermark en connector_states, el registro de exito y el
manejo del fallo fatal.

Lo que NO vive aqui (sigue en cada monitor, es especifico del dominio): la
resolucion de tickers/CIKs, el bucle de escaneo con su presupuesto de
descargas, la verificacion del emisor (13D/G) y los backfills (Form 4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.models.entities import ConnectorState


def utcnow() -> datetime:
    return datetime.now(UTC)


def connector_state(db: Session, tenant_id: int | None, connector: str) -> ConnectorState:
    """Fila de watermark del conector (una por connector+tenant), creada si falta."""
    state = db.scalar(
        select(ConnectorState).where(
            ConnectorState.connector == connector,
            ConnectorState.tenant_id.is_(tenant_id)
            if tenant_id is None
            else ConnectorState.tenant_id == tenant_id,
            ConnectorState.company_id.is_(None),
        )
    )
    if state is None:
        state = ConnectorState(tenant_id=tenant_id, connector=connector)
        db.add(state)
        db.flush()
    return state


def record_success(
    db: Session,
    state: ConnectorState,
    stats: dict[str, Any],
    *,
    extra_totals: dict[str, str] | None = None,
) -> None:
    """Watermark de corrida OK: runs, acumulados y last_run en metadata_.

    ``extra_totals`` mapea clave de stats -> clave acumulada en metadata_
    (p. ej. insider_monitor suma transactions_created -> transactions_total).
    """
    state.last_success_at = utcnow()
    state.consecutive_errors = 0
    state.last_error = None
    state.cursor = stats.get("status")
    meta = dict(state.metadata_ or {})
    meta["runs"] = int(meta.get("runs", 0)) + 1
    meta["filings_new_total"] = int(meta.get("filings_new_total", 0)) + stats["filings_new"]
    for stats_key, meta_key in (extra_totals or {}).items():
        meta[meta_key] = int(meta.get(meta_key, 0)) + stats[stats_key]
    meta["last_run"] = stats
    state.metadata_ = meta
    db.add(state)
    db.commit()


def record_fatal(
    db: Session,
    tenant_id: int | None,
    connector: str,
    stats: dict[str, Any],
    exc: Exception,
    *,
    public_reason: str | None = None,
) -> None:
    """Marca el fallo fatal en connector_states; el actor jamas recibe una excepcion.

    El mensaje de la excepcion puede traer secretos (URL con credenciales):
    ``last_error`` (persistido para ops, NO se sirve en ninguna respuesta) lo
    guarda con secretos redactados (#2900/#2864). En ``stats["errors"]``:
    - con ``public_reason`` solo va esa razon constante: el stats de ese
      monitor SI se sirve en la API (ownership.scan) y nada derivado de la
      excepcion puede viajar;
    - sin ella, stats conserva el detalle redactado (monitores cuyo stats no
      se sirve en ninguna ruta).

    Rollback ANTES de tocar nada mas: si el fallo vino de la sesion (p. ej.
    un commit roto), commitear sobre ella lanzaria PendingRollbackError y
    perderia el estado. Tras el rollback el estado se relee (o recrea): el
    objeto previo pudo quedar deshecho.
    """
    stats["status"] = "error"
    fatal_error = redact_secrets(f"{type(exc).__name__}: {exc}")[:1000]
    if public_reason is not None:
        stats["errors"].append(f"fatal: {public_reason}")
    else:
        stats["errors"].append(f"fatal: {fatal_error}")
    db.rollback()
    state = connector_state(db, tenant_id, connector)
    state.consecutive_errors = (state.consecutive_errors or 0) + 1
    state.last_error = fatal_error
    meta = dict(state.metadata_ or {})
    meta["runs"] = int(meta.get("runs", 0)) + 1
    meta["last_run"] = stats
    state.metadata_ = meta
    db.add(state)
    db.commit()
