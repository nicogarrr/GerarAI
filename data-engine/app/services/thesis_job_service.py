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
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, desc, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import WorkflowRun, WorkflowStepRun

logger = logging.getLogger(__name__)

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


def _live_phases(run: WorkflowRun) -> list[dict] | None:
    """Progreso en vivo publicado por el worker mientras genera (realqa-21).

    Las filas WorkflowStepRun solo se confirman al final (van dentro del
    SAVEPOINT de la generacion), asi que durante los ~50 s de trabajo el
    sondeo no veia ninguna fase y la UI decia «En cola». El worker publica
    aparte, en result_payload["progress"], la fase en curso y las ya hechas.
    """
    if run.status != "running":
        return None
    progress = (run.result_payload or {}).get("progress") if isinstance(run.result_payload, dict) else None
    if not isinstance(progress, dict) or not isinstance(progress.get("phases"), list):
        return None
    # Un intento recuperado no puede reutilizar la fase del worker anterior.
    # La identidad incluye el inicio, no solo el contador (compatibilidad con
    # registros viejos). Sin metadatos verificables no anunciamos progreso.
    try:
        started = _utc(run.started_at)
        progress_started = _utc(datetime.fromisoformat(progress["started_at"]))
        published = _utc(datetime.fromisoformat(progress["published_at"]))
        if (
            progress.get("attempt") != run.attempt
            or started is None
            or progress_started != started
            or published is None
            or published < started
            or published > datetime.now(UTC)
        ):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return [p for p in progress["phases"] if isinstance(p, dict) and p.get("name")]


def job_payload(run: WorkflowRun) -> dict:
    """Honest status payload: real phases and timestamps, never an ETA."""
    steps = sorted(
        (s for s in (run.steps or []) if s.attempt == run.attempt),
        key=lambda s: s.position,
    )
    # Una fila confirmada (refresh_sec) puede convivir con fases nuevas aun
    # dentro del SAVEPOINT. Solo el progreso del intento activo tiene prioridad;
    # los estados terminales siempre usan los pasos confirmados.
    live = _live_phases(run)
    if live is not None:
        phases = [
            {
                "name": p["name"],
                "status": p.get("status", "running"),
                "started_at": p.get("started_at"),
                "finished_at": p.get("finished_at"),
            }
            for p in live
        ]
        current = next((p["name"] for p in reversed(phases) if p["status"] == "running"), None)
    else:
        phases = [
            {
                "name": s.step_name,
                "status": s.status,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
            }
            for s in steps
        ]
        current = next((s.step_name for s in reversed(steps) if s.status == "running"), None)
    tracked = bool((run.input_payload or {}).get("tracked"))
    result = run.result_payload
    if isinstance(result, dict) and "progress" in result and run.status != "succeeded":
        result = {k: v for k, v in result.items() if k != "progress"} or None
    return {
        "id": run.id,
        "workflow_name": run.workflow_name,
        "status": run.status,
        "ticker": (run.input_payload or {}).get("ticker"),
        "force": (run.input_payload or {}).get("force"),
        "phases": phases,
        "current_phase": current,
        "total_phases": len(THESIS_PHASES) + (1 if tracked else 0),
        "result": result,
        "error_class": run.error_class,
        "error_message": run.error_message,
        "attempt": run.attempt,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _is_retryable_error(exc: BaseException) -> bool:
    """Classify delivery failures without importing the worker module eagerly."""
    import httpx
    import redis.exceptions as redis_exc
    from dramatiq.middleware.time_limit import TimeLimitExceeded
    from sqlalchemy import exc as sa_exc

    if isinstance(exc, TimeLimitExceeded):
        # El limite efectivo por entrega (TimeLimit del broker, 10 min por
        # defecto en dramatiq 2.2.1; el actor no lo sobrescribe) corto la
        # generacion: reintento acotado por MAX_ATTEMPTS, no fallo eterno ni
        # run "running" hasta el lease de 6 h. Es BaseException: sin listarlo
        # aqui no entraba jamas en el manejador de fallos.
        return True
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


def _record_preclaim_failure(db: Session, run_id: int, exc: BaseException) -> None:
    """Consume un intento cuando el fallo ocurre antes de reclamar el run.

    Relee la fila tras el rollback. Si otra entrega ya la reclamo (running con
    started_at reciente) no escribe nada. Cuenta el intento no reclamado como
    fallido (attempt = el que se iba a reclamar); transitorio con intentos
    restantes -> retrying, en otro caso failed. Condicional por status+attempt
    leidos: nunca pisa el estado de otra entrega.
    """
    db.rollback()
    row = db.execute(
        select(WorkflowRun.status, WorkflowRun.attempt, WorkflowRun.started_at)
        .where(WorkflowRun.id == run_id)
        .execution_options(include_all_tenants=True)
    ).one_or_none()
    if row is None or row.status in TERMINAL_STATUSES:
        db.rollback()
        return
    status, attempt, started = row.status, int(row.attempt or 1), _utc(row.started_at)
    if status == "running" and started is not None and datetime.now(UTC) - started < RUNNING_LEASE:
        db.rollback()
        return  # otra entrega es la duena viva
    # Numero del intento que ESTA entrega iba a reclamar (misma cuenta que el
    # reclamo normal): desde retrying/running el reclamo hace attempt+1; desde
    # queued usa el attempt actual. Se registra como el intento fallido, de modo
    # que el siguiente reclamo desde retrying suma +1 una sola vez.
    consumed = attempt + 1 if status in ("retrying", "running") else max(attempt, 1)
    retryable = _is_retryable_error(exc) and consumed < MAX_ATTEMPTS
    values: dict = {
        "status": "retrying" if retryable else "failed",
        "attempt": consumed,
        "error_class": type(exc).__name__,
        "error_message": (
            "Transient failure; delivery will be retried" if retryable else "Thesis generation failed"
        ),
        "updated_at": datetime.now(UTC),
    }
    if not retryable:
        values["finished_at"] = datetime.now(UTC)
    db.execute(
        update(WorkflowRun)
        .where(WorkflowRun.id == run_id, WorkflowRun.status == status, WorkflowRun.attempt == attempt)
        .values(**values)
        .execution_options(include_all_tenants=True)
    )
    db.commit()


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def build_run_guard(run: WorkflowRun, settings, store=None, db: Session | None = None):
    """Guard LLM por job de tesis, o None si esta desactivado (max_posts=0).

    run_id = ``thesis:<run.id>`` (sin intento): reintentos y re-entregas
    comparten contador. Inicializacion DURABLE fuera de Redis: el marcador
    ``input_payload["llm_guard"]`` (BD) guarda el deadline absoluto. Solo el
    primer claim sin marcador crea el contador (idempotente, nunca resetea uno
    vivo) y luego persiste el marcador. Con marcador, un contador ausente
    (expirado/desalojado/flush) NO se recrea: el guard aborta (counter_missing).
    El deadline se comprueba antes de CADA reserva, tambien en mitad de generate.
    Fail closed si el store no se puede construir. TTS/Telegram no son LLM y no
    pasan por este guard: un run aislado debe bloquearlos por configuracion.
    """
    import math
    import time

    from app.llm.run_guard import LLMGuardAbort, LLMRunGuard, RedisCounterStore

    max_posts = int(getattr(settings, "llm_run_guard_max_posts", 0) or 0)
    if max_posts <= 0:
        return None
    window = int(settings.llm_run_guard_window_seconds)
    if window <= 0:
        raise LLMGuardAbort("run_guard_window_expired")
    if store is None:
        try:
            import redis

            from app.core.redis_retry import no_retry

            client = redis.Redis.from_url(
                settings.redis_url, socket_connect_timeout=0.25, socket_timeout=0.5, retry=no_retry()
            )
            store = RedisCounterStore(client, ttl_seconds=window)
        except Exception:
            raise LLMGuardAbort("store_unavailable") from None
    hosts = frozenset(h.strip() for h in settings.llm_run_guard_allowed_hosts.split(",") if h.strip())
    models = frozenset(m.strip() for m in settings.llm_run_guard_allowed_models.split(",") if m.strip())
    run_key = f"thesis:{run.id}"
    payload_now = run.input_payload or {}
    now_ts = time.time()
    if "llm_guard" in payload_now:
        # Marcador PRESENTE: jamas se trata como ausente ni se reinicializa.
        marker = payload_now["llm_guard"]
        deadline = marker.get("deadline_ts") if isinstance(marker, dict) else None
        if (
            not isinstance(marker, dict)
            or isinstance(deadline, bool)
            or not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)
            or deadline <= 0
            or deadline > now_ts + window + 86400
        ):
            raise LLMGuardAbort("guard_marker_invalid")
        deadline_ts = float(deadline)
        if now_ts >= deadline_ts:
            raise LLMGuardAbort("run_guard_window_expired")
    else:
        if db is None:
            raise LLMGuardAbort("guard_marker_unavailable")
        deadline_ts = now_ts + window
        store.init(run_key, deadline_ts=deadline_ts)  # primero el contador...
        run.input_payload = {**payload_now, "llm_guard": {"deadline_ts": deadline_ts}}
        db.commit()  # ...despues el marcador durable; ninguna reserva antes
    try:
        return LLMRunGuard(
            run_id=run_key,
            allowed_hosts=hosts,
            allowed_models=models,
            max_posts=max_posts,
            max_tokens_per_request=int(settings.llm_run_guard_max_tokens_per_request),
            max_total_output_tokens=int(settings.llm_run_guard_max_total_output_tokens),
            store=store,
            deadline_ts=deadline_ts,
        )
    except ValueError:
        raise LLMGuardAbort("guard_misconfigured") from None


def _publish_live_progress(run_id: int, fence: int, started_at: datetime, phases: list[dict]) -> None:
    """Confirma el progreso en una sesion propia y corta, fuera del SAVEPOINT.

    Mejor esfuerzo: un fallo aqui nunca toca la generacion. Solo escribe si
    el run sigue siendo de este intento (attempt == fence) y en curso, asi un
    intento cercado no pisa el progreso del nuevo dueno. La fila final (exito
    o fallo) sustituye result_payload, de modo que el progreso no sobrevive.
    """
    try:
        with SessionLocal() as progress_db:
            progress_db.execute(
                update(WorkflowRun)
                .where(
                    WorkflowRun.id == run_id,
                    WorkflowRun.attempt == fence,
                    WorkflowRun.status == "running",
                    WorkflowRun.started_at == started_at,
                )
                .values(result_payload={"progress": {
                    "attempt": fence,
                    "started_at": started_at.isoformat(),
                    "published_at": datetime.now(UTC).isoformat(),
                    "phases": phases,
                }})
            )
            progress_db.commit()
    except Exception:  # noqa: BLE001 - el progreso es informativo
        logger.warning("no se pudo publicar el progreso del run %s", run_id, exc_info=True)


def _live_progress_supported(db: Session) -> bool:
    # SQLite (tests/dev) bloquea la base entera mientras la generacion tiene su
    # transaccion de escritura abierta: una segunda sesion esperaria el
    # busy-timeout en cada fase. En Postgres no hay conflicto: el worker solo
    # toma FOR KEY SHARE sobre el run al insertar los pasos.
    bind = db.get_bind()
    return getattr(getattr(bind, "dialect", None), "name", "") != "sqlite"


def run_thesis_job(run_id: int) -> None:
    """Run a thesis delivery with tenant context and recoverable retries."""
    import contextlib

    from dramatiq.middleware.time_limit import TimeLimitExceeded

    from app.llm.run_guard import activate

    guard_stack = contextlib.ExitStack()
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
        run.result_payload = None  # Nunca reciclar progreso de un intento anterior.
        if tenant is not None:
            db.info["tenant_id"] = tenant.id
            db.info["user_id"] = str(user_id)
            # This actor receives only run_id, so the broker middleware cannot
            # infer its tenant. Bind after validating the durable envelope,
            # and restore even when generation fails or this delivery is fenced.
            from app.llm.tenant_config import tenant_llm_config_scope
            from app.services.tenant_llm_settings_service import load_config_for_tenant

            try:
                guard_stack.enter_context(
                    tenant_llm_config_scope(load_config_for_tenant(db, tenant.id))
                )
            except (Exception, TimeLimitExceeded) as exc:
                # Antes del reclamo (commit de abajo) el intento no se habia
                # consumido: un fallo persistente aqui dejaba el run en
                # retrying/running con attempt fijo, sin llegar nunca a
                # MAX_ATTEMPTS. Se registra como fallo del intento.
                _record_preclaim_failure(db, run_id, exc)
                raise
        db.commit()
        # Fencing token del intento: si una entrega de recuperacion (lease
        # expirado, reconciler) toma el run MIENTRAS este intento genera,
        # intent +1 lo delata. Ni el commit de exito ni el manejador de
        # fallos de un intento cercado pueden pisar el estado del nuevo
        # dueno; el trabajo LLM duplicado en ese escenario patologico
        # (thread vivo >lease pese al TimeLimit) queda descartado, no
        # fusionado.
        fence = int(run.attempt or 1)

        state: dict[str, object] = {"position": 0, "open_step": None}
        publish_progress = _live_progress_supported(db)

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
            live = state.setdefault("live", [])
            if isinstance(live, list):
                if live:
                    live[-1]["status"] = "succeeded"
                    live[-1]["finished_at"] = now.isoformat()
                live.append({"name": name, "status": "running", "started_at": now.isoformat(), "finished_at": None})
                if publish_progress:
                    _publish_live_progress(run_id, fence, run.started_at, [dict(p) for p in live])

        try:
            # Guard por job (inactivo con max_posts=0). Dentro del try: un
            # fallo cerrado se registra como fallo del run, antes de la red.
            _guard = build_run_guard(run, settings, db=db)
            if _guard is not None:
                guard_stack.enter_context(activate(_guard))
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
            result_payload = {
                "thesis_version_id": thesis.id,
                "version": thesis.version,
                "status": thesis.status,
            }
            if financial_refresh is not None:
                result_payload["financial_refresh"] = financial_refresh
            # Cierre atomico: el UPDATE condicional ES el fence. No hay
            # lectura previa que pueda quedar obsoleta entre check y write:
            # si otra entrega reclamo el run (attempt cambio) en cualquier
            # momento anterior a esta sentencia, rowcount=0 y el rollback
            # descarta la tesis y los pasos de este intento cercado; el
            # nuevo dueno decide el estado final. (autoflush=False: los
            # pasos pendientes se insertan en el commit, misma transaccion.)
            claimed = db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id, WorkflowRun.attempt == fence)
                .values(
                    status="succeeded",
                    result_payload=result_payload,
                    error_class=None,
                    error_message=None,
                    finished_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            ).rowcount
            if claimed != 1:
                db.rollback()
                return
            db.commit()
        except (Exception, TimeLimitExceeded) as exc:
            # The rollback discards the step rows flushed by on_phase, so the
            # in-memory `open_step` is expunged and its identity is gone. The
            # progress already flushed is intentionally lost with the failed
            # attempt: the run row is what a reconciler reads, and a step that
            # survives a rolled-back attempt would describe work that was
            # undone. Capture the step NAME before the rollback so the failure
            # handler can re-create the step it was running.
            open_step_name = state["open_step_name"] if state.get("open_step") is not None else None
            db.rollback()
            retryable = _is_retryable_error(exc)
            terminal = not (retryable and fence < MAX_ATTEMPTS)
            values: dict = {
                "status": "failed" if terminal else "retrying",
                "error_class": type(exc).__name__,
                "error_message": (
                    "Thesis generation failed" if terminal else "Transient failure; delivery will be retried"
                ),
                "updated_at": datetime.now(UTC),
            }
            if terminal:
                values["finished_at"] = datetime.now(UTC)
            # Cierre atomico, mismo patron que el camino de exito: el UPDATE
            # condicional por attempt ES el fence (sin lectura previa que
            # pueda quedar obsoleta entre check y write). rowcount=0 significa
            # que otra entrega reclamo el run (o la fila ya no existe): este
            # intento cercado no escribe nada y el nuevo dueno decide.
            claimed = db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run_id, WorkflowRun.attempt == fence)
                .values(**values)
            ).rowcount
            if claimed != 1:
                db.rollback()
                raise
            if open_step_name is not None:
                step = WorkflowStepRun(
                    run_id=run_id,
                    step_name=open_step_name,
                    position=int(state["position"]),
                    attempt=fence,
                    status="failed" if terminal else "retrying",
                    started_at=now,
                    finished_at=datetime.now(UTC) if terminal else None,
                    error_class=type(exc).__name__,
                    tenant_id=tenant.id if tenant is not None else None,
                )
                db.add(step)
            db.commit()
            raise
    finally:
        guard_stack.close()
        db.close()
