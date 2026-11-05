"""Uniform workflow run envelope.

Every workflow execution — deterministic runner, MAF graph or direct service
call — gets one workflow_runs row plus one workflow_step_runs row per
executed step. The envelope provides:

- a truthful state machine (queued/running/succeeded/failed) per run;
- idempotent re-delivery: the same idempotency key never executes twice,
  the stored result is replayed instead;
- classified errors (error_class + message) on the run and the failing step.

Envelope writes are best-effort, like insider persistence: a failure to
record the envelope must never break the business result. Recording happens
in its own commits so a business rollback does not erase the trace.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import WorkflowRun, WorkflowStepRun
from app.services import tracing

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_commit(db: Session, context: str) -> bool:
    try:
        db.commit()
        return True
    except Exception:  # noqa: BLE001 - envelope must never break the workflow
        logger.warning("workflow envelope commit failed (%s)", context, exc_info=True)
        db.rollback()
        return False


class WorkflowEnvelope:
    """Recording wrapper around one workflow run."""

    def __init__(self, db: Session, run: WorkflowRun, *, replayed: bool = False) -> None:
        self.db = db
        self.run = run
        self.replayed = replayed
        # Stage 3: shadow tracing. Inerte salvo flag + keys + muestreo.
        self._tracer_token = None
        if not replayed:
            self.tracer = tracing.begin_trace(
                run.workflow_name,
                run_id=run.id,
                metadata={
                    "workflow_name": run.workflow_name,
                    "run_id": run.id,
                    "tenant_hash": tracing.tenant_hash(run.tenant_id),
                    "execution_mode": run.execution_mode,
                    "trigger": "api",
                    "input_fingerprint": tracing.input_fingerprint(run.input_payload),
                },
            )
            self._tracer_token = tracing.set_current_tracer(self.tracer)
        else:
            self.tracer = None

    def record_step(
        self,
        position: int,
        step_name: str,
        handler: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute one step, persisting its outcome. Re-raises on failure."""
        step = WorkflowStepRun(
            tenant_id=self.run.tenant_id,
            run_id=self.run.id,
            step_name=step_name,
            position=position,
            status="running",
            attempt=self.run.attempt,
            started_at=_utcnow(),
        )
        self.db.add(step)
        _safe_commit(self.db, f"step {step_name} start")
        from contextlib import nullcontext

        span = self.tracer.step(position, step_name) if self.tracer else nullcontext()
        try:
            with span:
                result = handler()
        except Exception as exc:
            step.status = "failed"
            step.error_class = type(exc).__name__
            step.error_message = str(exc)[:1000]
            step.finished_at = _utcnow()
            self.db.add(step)
            self.run.status = "failed"
            self.run.error_class = type(exc).__name__
            self.run.error_message = str(exc)[:1000]
            self.run.finished_at = _utcnow()
            self.db.add(self.run)
            _safe_commit(self.db, f"step {step_name} failure")
            if self.tracer:
                self.tracer.finish(status="failed", error_class=type(exc).__name__)
                if self._tracer_token is not None:
                    tracing.reset_current_tracer(self._tracer_token)
                    self._tracer_token = None
            raise
        step.status = "succeeded"
        # Async handlers resolve to a coroutine here; only persist real dicts.
        step.result_payload = result if isinstance(result, dict) else {"result_type": type(result).__name__}
        step.finished_at = _utcnow()
        self.db.add(step)
        _safe_commit(self.db, f"step {step_name} success")
        return result

    def finish(self, result_payload: dict[str, Any]) -> WorkflowRun:
        self.run.status = "succeeded"
        self.run.result_payload = result_payload
        self.run.finished_at = _utcnow()
        self.db.add(self.run)
        _safe_commit(self.db, "run finish")
        if self.tracer:
            self.tracer.finish(status="succeeded")
            if self._tracer_token is not None:
                tracing.reset_current_tracer(self._tracer_token)
                self._tracer_token = None
        return self.run

    def fail(self, exc: BaseException) -> None:
        """Cierra la corrida como fallida si un paso externo lanza."""
        self.run.status = "failed"
        self.run.error_class = type(exc).__name__
        self.run.error_message = str(exc)[:1000]
        self.run.finished_at = _utcnow()
        self.db.add(self.run)
        _safe_commit(self.db, "run failure")
        if self.tracer:
            self.tracer.finish(status="failed", error_class=type(exc).__name__)
            if self._tracer_token is not None:
                tracing.reset_current_tracer(self._tracer_token)
                self._tracer_token = None


def begin_run(
    db: Session,
    workflow_name: str,
    *,
    execution_mode: str | None = None,
    input_payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    tenant_id: int | None = None,
) -> WorkflowEnvelope:
    """Start a run envelope, or replay a prior success for the same key.

    Idempotency: when idempotency_key matches a prior succeeded run for the
    same workflow (and tenant), no new execution happens — the envelope
    carries the stored run with replayed=True and the caller returns its
    stored result. A key matching a failed run starts a fresh attempt.
    """
    if tenant_id is None:
        # La sesion real lleva el tenant activo; sin este valor el replay busca
        # tenant_id IS NULL y nunca encuentra la ejecucion previa (F393).
        active_tenant = db.info.get("tenant_id")
        tenant_id = active_tenant if isinstance(active_tenant, int) else None
    if idempotency_key:
        existing = db.scalar(
            select(WorkflowRun).where(
                WorkflowRun.workflow_name == workflow_name,
                WorkflowRun.idempotency_key == idempotency_key,
                WorkflowRun.tenant_id.is_(None) if tenant_id is None
                else WorkflowRun.tenant_id == tenant_id,
            )
        )
        if existing is not None and existing.status == "succeeded":
            return WorkflowEnvelope(db, existing, replayed=True)
        if existing is not None and existing.status == "running":
            # Reentrega mientras la primera ejecución sigue viva: no se lanza
            # una segunda. El llamador ve replayed=True y no repite efectos.
            return WorkflowEnvelope(db, existing, replayed=True)
        if existing is not None:
            # Un intento fallido con la MISMA clave reutiliza la fila y sube
            # attempt. Insertar otra violaría la unicidad (tenant, workflow,
            # key) y el commit best-effort se comía el error, dejando el run
            # sin id y los steps huérfanos. Sin tenant (solo tests/legado) la
            # unicidad no aplica y se conserva el intento nuevo.
            if tenant_id is None:
                existing = None
            else:
                existing.execution_mode = execution_mode or existing.execution_mode
                existing.input_payload = input_payload or {}
                existing.status = "running"
                existing.attempt = (existing.attempt or 1) + 1
                existing.started_at = _utcnow()
                existing.finished_at = None
                existing.error_class = None
                existing.error_message = None
                existing.result_payload = None
                db.add(existing)
                _safe_commit(db, "run retry")
                return WorkflowEnvelope(db, existing)

    run = WorkflowRun(
        tenant_id=tenant_id,
        workflow_name=workflow_name,
        execution_mode=execution_mode,
        status="running",
        idempotency_key=idempotency_key,
        input_payload=input_payload or {},
        attempt=1,
        started_at=_utcnow(),
    )
    db.add(run)
    if not _safe_commit(db, "run start") and idempotency_key:
        # Carrera entre dos primeras entregas: la otra insertó la fila. Se
        # recupera en vez de seguir con un run sin id.
        raced = db.scalar(
            select(WorkflowRun).where(
                WorkflowRun.workflow_name == workflow_name,
                WorkflowRun.idempotency_key == idempotency_key,
                WorkflowRun.tenant_id.is_(None) if tenant_id is None
                else WorkflowRun.tenant_id == tenant_id,
            )
        )
        if raced is not None:
            return WorkflowEnvelope(db, raced, replayed=raced.status == "succeeded")
    return WorkflowEnvelope(db, run)
