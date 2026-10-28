"""Registro de ejecuciones de la evaluacion DCA (solo observabilidad).

No participa en el calculo de niveles: ``evaluate_watchlist`` no se toca.
Todo aqui es a prueba de fallos: si registrar falla, la evaluacion sigue y el
fallo solo se anota en el log.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.core.tenancy import tenant_filters
from app.models import DcaEvaluationRun

logger = logging.getLogger(__name__)

# El actor tiene time_limit de 30 min: una fila "running" mas vieja que esto
# ya no esta corriendo, la mato un reinicio o el limite de tiempo.
STALE_RUNNING_AFTER = timedelta(minutes=40)
KEEP_RUNS = 60
_DETAIL_LIMIT = 500


def _trim(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out = []
    for entry in (items or [])[:_DETAIL_LIMIT]:
        out.append({k: entry[k] for k in ("symbol", "reason", "error", "last_price_date") if k in entry})
    return out


def start_run(db: Session, trigger: str) -> DcaEvaluationRun | None:
    try:
        row = DcaEvaluationRun(
            tenant_id=db.info.get("tenant_id"),
            trigger=trigger,
            status="running",
            started_at=datetime.now(UTC),
            detail={},
        )
        db.add(row)
        db.commit()
        return row
    except Exception:  # noqa: BLE001 - observabilidad, nunca frena la evaluacion
        logger.warning("dca run log: no se pudo registrar el inicio", exc_info=True)
        _safe_rollback(db)
        return None


def finish_run(
    db: Session,
    row: DcaEvaluationRun | None,
    *,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    if row is None:
        return
    try:
        summary = summary or {}
        row.finished_at = datetime.now(UTC)
        row.status = "error" if error else "ok"
        # El texto del error se muestra en la watchlist (last_run.error y el
        # motivo por ticker). Una excepcion de httpx o de la base de datos trae
        # la URL con ?apikey= o el DSN con la password: se redacta ANTES de
        # recortar a 300, para que el recorte no deje medio secreto sin tapar.
        row.error = (error or None) and redact_secrets(error)[:300]
        row.tracked = int(summary.get("tracked", 0))
        row.evaluated = int(summary.get("evaluated", 0))
        row.skipped_count = len(summary.get("skipped", []))
        row.errors_count = len(summary.get("errors", []))
        row.alerted_count = len(summary.get("alerted", []))
        row.params_version = summary.get("params_version")
        row.detail = {
            "skipped": _trim(summary.get("skipped")),
            "errors": _trim(summary.get("errors")),
            # El detalle por simbolo esta acotado: si no cabe, se declara.
            "truncated": len(summary.get("skipped", [])) > _DETAIL_LIMIT or len(summary.get("errors", [])) > _DETAIL_LIMIT,
        }
        db.commit()
        _prune(db)
    except Exception:  # noqa: BLE001
        logger.warning("dca run log: no se pudo registrar el final", exc_info=True)
        _safe_rollback(db)


def _prune(db: Session) -> None:
    keep = db.scalars(
        select(DcaEvaluationRun.id)
        .where(*tenant_filters(db, DcaEvaluationRun))
        .order_by(DcaEvaluationRun.started_at.desc())
        .limit(KEEP_RUNS)
    ).all()
    if len(keep) < KEEP_RUNS:
        return
    db.execute(
        delete(DcaEvaluationRun).where(*tenant_filters(db, DcaEvaluationRun), DcaEvaluationRun.id.notin_(keep))
    )
    db.commit()


def _safe_rollback(db: Session) -> None:
    try:
        db.rollback()
    except Exception:  # noqa: BLE001
        pass


def latest_run(db: Session) -> DcaEvaluationRun | None:
    return db.scalar(
        select(DcaEvaluationRun)
        .where(*tenant_filters(db, DcaEvaluationRun))
        .order_by(DcaEvaluationRun.started_at.desc(), DcaEvaluationRun.id.desc())
        .limit(1)
    )


def run_payload(row: DcaEvaluationRun | None, now: datetime | None = None) -> dict[str, Any] | None:
    """Estado de la ultima ejecucion para la API. ``status``:
    ok | error | running | interrupted (running que ya no puede estar vivo)."""
    if row is None:
        return None
    now = now or datetime.now(UTC)
    status = "running" if row.status == "queued" else row.status
    started = row.started_at if row.started_at.tzinfo else row.started_at.replace(tzinfo=UTC)
    if status == "running" and now - started > STALE_RUNNING_AFTER:
        status = "interrupted"
    return {
        "status": status,
        "trigger": row.trigger,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "tracked": row.tracked,
        "evaluated": row.evaluated,
        "skipped": row.skipped_count,
        "errors": row.errors_count,
        "alerted": row.alerted_count,
        # Filas guardadas antes de redactar al escribir: se redacta tambien al leer.
        "error": redact_secrets(row.error) if row.error else row.error,
        "skipped_detail": (row.detail or {}).get("skipped", []),
        "errors_detail": (row.detail or {}).get("errors", []),
    }


def item_evaluation(symbol: str, has_state: bool, run: dict[str, Any] | None) -> dict[str, str | None]:
    """Por que un ticker no tiene nivel: ``evaluated`` | ``never_run`` |
    ``job_failed`` | ``skipped`` (con motivo) | ``running`` | ``pending`` (hubo
    ejecucion y este ticker no figura) | ``unknown`` (detalle truncado).
    ``never_run`` solo si no consta NINGUNA ejecucion."""
    if has_state:
        return {"status": "evaluated", "reason": None}
    if run is None:
        return {"status": "never_run", "reason": None}
    if run["status"] in ("error", "interrupted"):
        return {"status": "job_failed", "reason": run.get("error") or run["status"]}
    for entry in run.get("errors_detail", []):
        if entry.get("symbol") == symbol:
            return {"status": "job_failed", "reason": entry.get("error") or "error"}
    for entry in run.get("skipped_detail", []):
        if entry.get("symbol") == symbol:
            return {"status": "skipped", "reason": entry.get("reason")}
    if run["status"] == "running":
        return {"status": "running", "reason": None}
    listed_all = run.get("skipped", 0) <= len(run.get("skipped_detail", [])) and run.get("errors", 0) <= len(
        run.get("errors_detail", [])
    )
    if not listed_all:
        # El detalle guardado no cubre todos los omitidos/errores: no se puede
        # afirmar ni "nunca ejecutado" ni "no estaba en la ejecucion".
        return {"status": "unknown", "reason": "detalle de la ultima ejecucion truncado"}
    return {"status": "pending", "reason": "no figuraba en la ultima ejecucion"}
