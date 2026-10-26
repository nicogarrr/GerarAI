"""Async thesis generation jobs (user preference 2026-09-22: generation may
take longer and run in the background; quality/provenance over latency).

Contract:
- POST /api/thesis/generate-async enqueues a durable job on the workflow-run
  envelope and returns 202 immediately.
- GET /api/thesis/jobs/{id} exposes the HONEST state: queued/running with the
  real current phase (recorded when the generator actually enters it),
  succeeded/failed with timestamps. No invented ETAs anywhere.
- Idempotent enqueue: same ticker+force while a job is active returns the
  existing job instead of duplicating work.
- Retry-safe: ThesisService.generate is atomic and fingerprint-idempotent, so
  a Dramatiq retry resumes safely; re-entry guards prevent double runs.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, desc, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import WorkflowRun, WorkflowStepRun

WORKFLOW_NAME = "GenerateThesisWorkflow"
ACTIVE_STATUSES = ("queued", "running", "retrying", "dispatch_failed")
TERMINAL_STATUSES = ("succeeded", "failed")
MAX_ATTEMPTS = 3
RUNNING_LEASE = timedelta(hours=6)
DISPATCH_RECHECK = timedelta(minutes=5)

# Real phases instrumented inside ThesisService._generate_atomic. Order matters.
THESIS_PHASES: tuple[str, ...] = (
    "collect_evidence",
    "build_fundamental_model",
    "run_valuation",
    "persist_valuation_snapshot",
    "source_audit",
    "compose_thesis",
    "persist_thesis",
)


def idempotency_key_for(ticker: str, force: bool, request_id: str | None = None) -> str:
    key = f"thesis-gen:{ticker.upper()}:{bool(force)}"
    if request_id:
        key += f":{request_id}"
    return key


def _find_by_key(db: Session, key: str, tenant_id: int | None = None) -> WorkflowRun | None:
    statement = select(WorkflowRun).where(
        WorkflowRun.workflow_name == WORKFLOW_NAME,
        WorkflowRun.idempotency_key == key,
    )
    if tenant_id is not None:
        statement = statement.where(WorkflowRun.tenant_id == tenant_id)
    return db.scalar(statement.order_by(desc(WorkflowRun.id)).limit(1))


def _dispatch_run(run: WorkflowRun) -> None:
    from app.workers.dramatiq_app import generate_thesis_job

    generate_thesis_job.send(run.id)


def _lock_generation(db: Session, tenant_id: int | None, ticker: str, force: bool) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    raw = f"thesis-enqueue:{tenant_id}:{ticker.upper()}:{bool(force)}".encode()
    key = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def _earlier_active_run(db: Session, run: WorkflowRun, ticker: str, force: bool) -> WorkflowRun | None:
    statement = select(WorkflowRun).where(
        WorkflowRun.workflow_name == WORKFLOW_NAME,
        WorkflowRun.id < run.id,
        WorkflowRun.status.in_(ACTIVE_STATUSES),
        WorkflowRun.input_payload["ticker"].as_string() == ticker.upper(),
        WorkflowRun.input_payload["force"].as_boolean() == bool(force),
    )
    if run.tenant_id is not None:
        statement = statement.where(WorkflowRun.tenant_id == run.tenant_id)
    return db.scalar(statement.order_by(WorkflowRun.id).limit(1))


def enqueue_generation(
    db: Session, ticker: str, force: bool = False, request_id: str | None = None,
    *, tracked: bool = False,
) -> tuple[WorkflowRun, bool]:
    """Return a durable run, re-dispatching an unclaimed run when necessary.

    The idempotency key is a permanent request key, not an attempt key. A
    terminal run is therefore returned as a replay instead of attempting an
    insert that violates ``uq_workflow_runs_idempotency``. Active ticker/force
    runs are reused even across distinct click IDs. A server-side reconciler
    re-dispatches rows that could not reach the broker without a user request.
    """
    key = idempotency_key_for(ticker, force, request_id)
    tenant_id = db.info.get("tenant_id")
    user_id = str(db.info.get("user_id") or "").strip() or None
    payload: dict = {"ticker": ticker.upper(), "force": bool(force), "attempt": 1}
    if tracked:
        payload["tracked"] = True
    if tenant_id is not None:
        payload["tenant_id"] = int(tenant_id)
    if user_id is not None:
        payload["user_id"] = user_id

    # A UUID is a request replay key, not permission to start another active
    # generation after the user navigates away and comes back.
    # Dos POST concurrentes (pestanas, dispositivos) con click IDs distintos
    # llegan aqui a la vez: sin serializar, ambos ven "no hay activo" e insertan.
    # En Postgres un lock transaccional por tenant+ticker+force los ordena; el
    # lock se libera con el commit/rollback de la sesion.
    _lock_generation(db, tenant_id, ticker, force)
    active = latest_generation(db, ticker, active_only=True, force=force)
    existing = _find_by_key(db, key, tenant_id) or active
    # Idempotencia: un run que ya termino bien se devuelve tal cual (replay),
    # pero uno FALLIDO no es un resultado reutilizable - el front dice
    # "puedes reintentar", asi que reintentar debe re-despachar de verdad.
    if existing is not None and existing.status == "succeeded":
        return existing, False
    if existing is not None:
        retrying_failed = existing.status == "failed"
        needs_dispatch = (
            retrying_failed
            or existing.status == "dispatch_failed"
            or (existing.status == "queued" and not (existing.input_payload or {}).get("dispatch_sent_at"))
        )
        if needs_dispatch:
            if retrying_failed:
                existing.attempt = int(existing.attempt or 1) + 1
                existing.started_at = None
                existing.finished_at = None
                db.commit()
            dispatch_generation(db, existing)
        return existing, False

    run = WorkflowRun(
        tenant_id=tenant_id,
        workflow_name=WORKFLOW_NAME,
        execution_mode="async_dramatiq",
        status="queued",
        idempotency_key=key,
        input_payload=payload,
    )
    db.add(run)
    try:
        db.flush()
        # Red de seguridad sin lock (SQLite en tests/dev): si otra sesion ya
        # dejo un run activo de este ticker+force con id menor, gana ese y el
        # nuestro (aun sin publicar) se descarta.
        rival = _earlier_active_run(db, run, ticker, force)
        if rival is not None:
            db.rollback()
            return rival, False
        db.commit()
    except IntegrityError:
        db.rollback()
        raced = _find_by_key(db, key, tenant_id)
        if raced is not None:
            return raced, False
        raise
    db.refresh(run)

    dispatch_generation(db, run)
    return run, True


def latest_generation(
    db: Session, ticker: str, *, active_only: bool = False, force: bool | None = None
) -> WorkflowRun | None:
    # ORM tenant scope applies here just as it does to GET /jobs/{id}.
    statement = select(WorkflowRun).where(WorkflowRun.workflow_name == WORKFLOW_NAME)
    statement = statement.where(WorkflowRun.input_payload["ticker"].as_string() == ticker.upper())
    if active_only:
        statement = statement.where(WorkflowRun.status.in_(ACTIVE_STATUSES))
    if force is not None:
        statement = statement.where(WorkflowRun.input_payload["force"].as_boolean() == force)
    return db.scalar(statement.order_by(desc(WorkflowRun.id)).limit(1))


def dispatch_generation(db: Session, run: WorkflowRun) -> bool:
    # Publish only AFTER making the run claimable. Sending first left a race:
    # a fast worker saw dispatch_failed and discarded the only delivery.
    db.refresh(run, with_for_update=True)
    if run.status not in ("queued", "dispatch_failed", "failed"):
        db.commit()
        return True
    run.status = "queued"
    run.error_class = None
    run.error_message = None
    db.commit()
    try:
        _dispatch_run(run)
    except Exception as exc:
        db.refresh(run)
        if run.status == "queued":
            run.status = "dispatch_failed"
            run.error_class = type(exc).__name__
            run.error_message = "Thesis job dispatch failed"
            db.commit()
        return False
    db.refresh(run)
    payload = dict(run.input_payload or {})
    payload["dispatch_sent_at"] = datetime.now(UTC).isoformat()
    payload["attempt"] = run.attempt
    run.input_payload = payload
    db.commit()
    return True


def _redeliver_interrupted(db: Session, run: WorkflowRun) -> bool:
    """Re-envia el mensaje del actor para un run cuya unica entrega murio.

    No reescribe status: run_thesis_job reclama el lease expirado (running ->
    retrying con attempt+1) o continua el reintento perdido (retrying), y sus
    guards de lease fresco/terminal descartan cualquier copia que choque con
    un worker sano, asi que una re-entrega nunca duplica la generacion.
    Tras un envio exitoso se sella la entrega (recovery_sent_at, que tambien
    renueva updated_at) para que el tick siguiente del reconciler no
    multiplique despachos; si esta entrega tambien se pierde, el run vuelve
    a ser elegible pasado DISPATCH_RECHECK.
    """
    db.refresh(run, with_for_update=True)
    now = datetime.now(UTC)
    still_interrupted = run.status == "retrying" or (
        run.status == "running"
        and (run.started_at is None or _utc(run.started_at) < now - RUNNING_LEASE)
    )
    if not still_interrupted:
        return True
    try:
        _dispatch_run(run)
    except Exception:
        return False
    payload = dict(run.input_payload or {})
    payload["recovery_sent_at"] = now.isoformat()
    run.input_payload = payload
    db.commit()
    return True


def reconcile_thesis_dispatches() -> dict:
    """Recover the durable outbox without a browser or another user POST.

    Queued rows are re-delivered after five minutes, including publish/commit
    gaps and lost Redis messages. Runs whose only delivery was interrupted
    (worker muerto a mitad de la generacion: status "running" con el lease
    ya expirado; o "retrying" cuyo reintento de dramatiq se perdio con la
    cola) get ONE fresh actor message through _redeliver_interrupted: the
    worker-side lease/attempt guards own every status change, so a healthy
    active run is never restarted and a terminal one never replays.
    """
    stats = {"redispatched": 0, "dispatch_failed": 0}
    with SessionLocal() as db:
        now = datetime.now(UTC)
        runs = db.scalars(
            select(WorkflowRun)
            .where(
                WorkflowRun.workflow_name == WORKFLOW_NAME,
                WorkflowRun.status.in_(("queued", "dispatch_failed")),
                WorkflowRun.updated_at < now - DISPATCH_RECHECK,
            )
            .order_by(WorkflowRun.id)
            .limit(100)
        ).all()
        for run in runs:
            success = dispatch_generation(db, run)
            stats["redispatched" if success else "dispatch_failed"] += 1
        # updated_at < DISPATCH_RECHECK en ambas ramas: tras una re-entrega
        # sellada (o un worker que ya reclamo el run) el tick de 1 min no
        # multiplica despachos; un run sano en "running" tiene started_at
        # fresco y jamas entra aqui.
        interrupted = db.scalars(
            select(WorkflowRun)
            .where(
                WorkflowRun.workflow_name == WORKFLOW_NAME,
                WorkflowRun.updated_at < now - DISPATCH_RECHECK,
                or_(
                    WorkflowRun.status == "retrying",
                    and_(
                        WorkflowRun.status == "running",
                        or_(
                            WorkflowRun.started_at.is_(None),
                            WorkflowRun.started_at < now - RUNNING_LEASE,
                        ),
                    ),
                ),
            )
            .order_by(WorkflowRun.id)
            .limit(100)
        ).all()
        for run in interrupted:
            success = _redeliver_interrupted(db, run)
            stats["redispatched" if success else "dispatch_failed"] += 1
    return stats


def job_payload(run: WorkflowRun) -> dict:
    """Honest status payload: real phases and timestamps, never an ETA."""
    steps = sorted(run.steps or [], key=lambda s: s.position)
    return {
        "id": run.id,
        "workflow_name": run.workflow_name,
        "status": run.status,
        "ticker": (run.input_payload or {}).get("ticker"),
        "force": (run.input_payload or {}).get("force"),
        "phases": [
            {
                "name": s.step_name,
                "status": s.status,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
            }
            for s in steps
        ],
        "current_phase": next((s.step_name for s in reversed(steps) if s.status == "running"), None),
        "result": run.result_payload,
        "error_class": run.error_class,
        "error_message": run.error_message,
        "attempt": run.attempt,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _is_retryable_error(exc: Exception) -> bool:
    """Classify delivery failures without importing the worker module eagerly."""
    import httpx
    import redis.exceptions as redis_exc
    from sqlalchemy import exc as sa_exc

    if isinstance(
        exc,
        (
            ConnectionError,
            TimeoutError,
            sa_exc.OperationalError,
            sa_exc.TimeoutError,
            redis_exc.RedisError,
            httpx.TimeoutException,
            httpx.TransportError,
        ),
    ):
        return True
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def run_thesis_job(run_id: int) -> None:
    """Run a thesis delivery with tenant context and recoverable retries."""
    db = SessionLocal()
    try:
        # Bootstrap cross-tenant: el worker recibe solo run_id y el tenant
        # viaja dentro del payload del run; hay que leerlo antes de poder
        # fijar db.info["tenant_id"]. No es una lectura expuesta a un tenant.
        run = db.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .with_for_update()
            .execution_options(include_all_tenants=True)
        )
        if run is None or run.status in TERMINAL_STATUSES or run.status == "dispatch_failed":
            return

        now = datetime.now(UTC)
        if run.status == "running":
            started = _utc(run.started_at)
            if started is not None and now - started < RUNNING_LEASE:
                return
            # Lease expirado: el worker anterior murio a mitad del intento.
            # Cada recuperacion consume un intento; sin tope, un ticker que
            # tumba al worker (p. ej. OOM) re-botaria cada 6 h para siempre
            # en vez de quedar en un fallo terminal honesto.
            if int(run.attempt or 1) >= MAX_ATTEMPTS:
                run.status = "failed"
                run.error_class = "RecoverableRunningState"
                run.error_message = (
                    "Thesis generation failed after repeated interrupted deliveries"
                )
                run.finished_at = now
                db.commit()
                return
            run.status = "retrying"
            run.error_class = "RecoverableRunningState"
            run.error_message = "A previous worker lease expired; retrying"
            db.commit()

        settings = get_settings()
        payload = run.input_payload or {}
        tenant_id = payload.get("tenant_id")
        user_id = payload.get("user_id")
        tenant = None
        try:
            tenant_id_int = int(tenant_id) if tenant_id is not None else None
        except (TypeError, ValueError):
            tenant_id_int = None
        if tenant_id_int is not None and user_id:
            from app.models import Tenant

            tenant = db.get(Tenant, tenant_id_int, execution_options={"include_all_tenants": True})
        if tenant_id is not None and (tenant is None or tenant.status != "active"):
            run.status = "failed"
            run.error_class = "TenantAccessError"
            run.error_message = "Job tenant is not active"
            run.finished_at = now
            db.commit()
            raise ValueError(run.error_message)
        if (settings.research_auth_required or settings.is_production) and (
            tenant_id_int is None or not user_id
        ):
            run.status = "failed"
            run.error_class = "MissingTenantContext"
            run.error_message = "Thesis job is missing tenant/user context"
            run.finished_at = now
            db.commit()
            raise ValueError(run.error_message)

        if run.status == "retrying":
            run.attempt = max(int(run.attempt or 1) + 1, 2)
        else:
            run.attempt = max(int(run.attempt or 1), 1)
        payload["attempt"] = run.attempt
        run.input_payload = payload
        run.status = "running"
        # Cada intento arranca con su propio started_at: conservar el del
        # intento muerto dejaba el lease YA expirado, y cualquier entrega
        # duplicada (o la re-entrega del reconciler) re-disparaba la
        # recuperacion a mitad de la generacion en curso.
        run.started_at = now
        run.finished_at = None
        if tenant is not None:
            db.info["tenant_id"] = tenant.id
            db.info["user_id"] = str(user_id)
        db.commit()

        state: dict[str, object] = {"position": 0, "open_step": None}

        def on_phase(name: str) -> None:
            now = datetime.now(UTC)
            previous = state["open_step"]
            if previous is not None:
                previous.status = "succeeded"
                previous.finished_at = now
            state["position"] = int(state["position"]) + 1
            step = WorkflowStepRun(
                run_id=run.id,
                step_name=name,
                position=int(state["position"]),
                attempt=int(run.attempt or 1),
                status="running",
                started_at=now,
                tenant_id=tenant.id if tenant is not None else None,
            )
            db.add(step)
            # flush, never commit: ThesisService.generate() holds a SAVEPOINT
            # open for the whole generation and a commit here closes it, which
            # made the documented atomicity impossible and turned any later
            # failure into a ResourceClosedError that masked the real cause.
            # Progress stays visible in the same transaction; the failure
            # handler re-creates the step it was running.
            db.flush()
            state["open_step"] = step
            state["open_step_name"] = name

        try:
            from app.services.company_enrichment_service import ensure_company_stub
            from app.services.thesis_service import ThesisService

            # Network enrichment belongs to the worker, never the enqueue
            # request (two 15 s Finnhub calls used to precede persistence).
            ensure_company_stub(db, payload["ticker"])
            # El stub persiste por contrato ("si falla, queda el stub"): se
            # commitea aqui para no arrastrar su INSERT ni la tx de lectura
            # durante las llamadas de red de enriquecimiento/SEC que siguen.
            db.commit()
            financial_refresh = None
            kwargs = {}
            if payload.get("tracked"):
                from app.services.async_bridge import run_from_any_context
                from app.services.company_resolver import resolve_company
                from app.services.tracked_financial_refresh import refresh_free_financials

                on_phase("refresh_sec")
                db.commit()  # SEC owns its refresh transaction, outside thesis savepoint.
                company = resolve_company(db, payload["ticker"])
                if company is None:
                    raise ValueError("No se pudo resolver la empresa para SEC")
                # Cierra la tx de lectura de resolve_company antes del refresh
                # de red (largo); expire_on_commit=False mantiene `company`.
                db.commit()
                financial_refresh = run_from_any_context(refresh_free_financials(db, company))
                kwargs["stored_evidence_only"] = True
                kwargs["refresh_receipt"] = financial_refresh
            thesis = ThesisService().generate(
                db,
                payload["ticker"],
                force_new_version=payload.get("force", False),
                phase_callback=on_phase,
                **kwargs,
            )
            open_step = state["open_step"]
            if open_step is not None:
                open_step.status = "succeeded"
                open_step.finished_at = datetime.now(UTC)
            run.status = "succeeded"
            result_payload = {
                "thesis_version_id": thesis.id,
                "version": thesis.version,
                "status": thesis.status,
            }
            if financial_refresh is not None:
                result_payload["financial_refresh"] = financial_refresh
            run.result_payload = result_payload
            run.error_class = None
            run.error_message = None
            run.finished_at = datetime.now(UTC)
            db.commit()
        except Exception as exc:
            # The rollback discards the step rows flushed by on_phase, so the
            # in-memory `open_step` is expunged and its identity is gone. The
            # progress already flushed is intentionally lost with the failed
            # attempt: the run row is what a reconciler reads, and a step that
            # survives a rolled-back attempt would describe work that was
            # undone. Capture the step NAME before the rollback so the failure
            # handler can re-create the step it was running.
            open_step_name = state["open_step_name"] if state.get("open_step") is not None else None
            db.rollback()
            # Recuperacion por run_id tras el rollback: el run ya fue validado
            # contra su tenant al arrancar; este GET no es una lectura expuesta.
            run = db.get(WorkflowRun, run_id, execution_options={"include_all_tenants": True})
            retryable = _is_retryable_error(exc)
            if run is not None:
                if open_step_name is not None:
                    step = WorkflowStepRun(
                        run_id=run.id,
                        step_name=open_step_name,
                        position=int(state["position"]),
                        attempt=int(run.attempt or 1),
                        status="retrying" if retryable else "failed",
                        started_at=now,
                        finished_at=None if retryable else datetime.now(UTC),
                        error_class=type(exc).__name__,
                        tenant_id=tenant.id if tenant is not None else None,
                    )
                    db.add(step)
                run.error_class = type(exc).__name__
                run.error_message = (
                    "Transient failure; delivery will be retried" if retryable else "Thesis generation failed"
                )
                if retryable and int(run.attempt or 1) < MAX_ATTEMPTS:
                    run.status = "retrying"
                else:
                    run.status = "failed"
                    run.finished_at = datetime.now(UTC)
                db.commit()
            raise
    finally:
        db.close()
