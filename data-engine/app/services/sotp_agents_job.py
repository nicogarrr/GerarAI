"""Job en segundo plano «Generar con expertos» del desglose por partes.

Mismo sobre durable que la tesis (``workflow_runs`` + Dramatiq, cola
``thesis``) pero con su propio nombre de workflow: un clic encola, el actor
corre el valorador SOTP del equipo de expertos y guarda la «propuesta de los
agentes». El estado es honesto (queued/running/succeeded/failed) y sin ETA.
Una corrida activa del mismo tenant y ticker se reutiliza (no se duplica).
La tesis también genera la propuesta al terminar (``thesis_job_service``);
este job es el «regenerar solo el desglose».
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.entities import WorkflowRun

logger = logging.getLogger(__name__)

WORKFLOW_NAME = "GenerateSotpAgentsWorkflow"
ACTIVE_STATUSES = ("queued", "running")
#: Una corrida activa más vieja que esto se da por muerta (el worker se reinició).
STALE_AFTER = timedelta(minutes=20)


def job_payload(run: WorkflowRun | None) -> dict | None:
    if run is None:
        return None
    result = dict(run.result_payload or {})
    return {
        "id": run.id,
        "status": run.status,
        "ticker": (run.input_payload or {}).get("ticker"),
        "result": {k: result.get(k) for k in ("status", "value_per_share", "problems", "llm_calls")} if result else None,
        "error_class": run.error_class,
        "created_at": run.created_at.isoformat() if getattr(run, "created_at", None) else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def latest_run(db: Session, ticker: str) -> WorkflowRun | None:
    # El ámbito ORM por tenant filtra la consulta como en /api/thesis/jobs.
    return db.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.workflow_name == WORKFLOW_NAME,
               WorkflowRun.input_payload["ticker"].as_string() == ticker.upper())
        .order_by(desc(WorkflowRun.id))
        .limit(1)
    )


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _dispatch(run: WorkflowRun) -> None:
    from app.workers.dramatiq_app import generate_sotp_agents_job

    generate_sotp_agents_job.send(run.id)


def enqueue(db: Session, ticker: str, *, dispatch=None) -> tuple[WorkflowRun, bool]:
    """Encola (o devuelve la activa). ``dispatch`` inyectable en tests."""
    ticker = ticker.upper()
    tenant_id = db.info.get("tenant_id")
    user_id = str(db.info.get("user_id") or "").strip() or None
    active = latest_run(db, ticker)
    now = datetime.now(UTC)
    if active is not None and active.status in ACTIVE_STATUSES:
        stamp = _utc(active.started_at) or _utc(getattr(active, "created_at", None))
        if stamp is None or now - stamp < STALE_AFTER:
            return active, False
        active.status = "failed"
        active.error_class = "StaleRun"
        active.error_message = "El trabajo anterior no terminó (worker reiniciado)"
        active.finished_at = now
    payload: dict = {"ticker": ticker}
    if tenant_id is not None:
        payload["tenant_id"] = int(tenant_id)
    if user_id is not None:
        payload["user_id"] = user_id
    run = WorkflowRun(
        tenant_id=tenant_id,
        workflow_name=WORKFLOW_NAME,
        execution_mode="async_dramatiq",
        status="queued",
        idempotency_key=f"sotp-agents:{ticker}:{uuid.uuid4().hex}",
        input_payload=payload,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        (dispatch or _dispatch)(run)
    except Exception as exc:  # noqa: BLE001 - sin broker no hay trabajo: fallo honesto
        run.status = "failed"
        run.error_class = type(exc).__name__
        run.error_message = "No se pudo encolar el trabajo"
        run.finished_at = datetime.now(UTC)
        db.commit()
    return run, True


def run_job(run_id: int, *, reasoner=None, session_factory=None) -> None:
    """Ejecuta una corrida encolada: contexto de tenant, valorador SOTP y estado final."""
    import contextlib

    from app.services.company_resolver import resolve_company
    from app.services.expert_team.sotp_valuer import generate_sotp_proposal

    db = (session_factory or SessionLocal)()
    stack = contextlib.ExitStack()
    try:
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == run_id)
                        .execution_options(include_all_tenants=True))
        if run is None or run.workflow_name != WORKFLOW_NAME or run.status not in ACTIVE_STATUSES:
            return
        payload = dict(run.input_payload or {})
        tenant_id = payload.get("tenant_id")
        if tenant_id is not None:
            db.info["tenant_id"] = int(tenant_id)
            db.info["user_id"] = payload.get("user_id")
            try:
                from app.llm.tenant_config import tenant_llm_config_scope
                from app.services.tenant_llm_settings_service import load_config_for_tenant

                stack.enter_context(tenant_llm_config_scope(load_config_for_tenant(db, int(tenant_id))))
            except Exception as exc:  # noqa: BLE001 - sin configuración propia, la de la app
                logger.info("sotp agents: sin config LLM del tenant (%s)", type(exc).__name__)
        run.status = "running"
        run.started_at = datetime.now(UTC)
        db.commit()
        company = resolve_company(db, payload.get("ticker") or "")
        if company is None:
            outcome = {"status": "no_company", "problems": ["empresa desconocida"]}
        else:
            outcome = generate_sotp_proposal(db, company, reasoner=reasoner, trigger="button").as_dict()
        run.result_payload = outcome
        run.status = "succeeded" if outcome.get("status") in ("stored", "cached") else "failed"
        run.error_class = None if run.status == "succeeded" else f"sotp:{outcome.get('status')}"
        run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("sotp agents job %s falló", run_id)
        try:
            run = db.get(WorkflowRun, run_id, execution_options={"include_all_tenants": True})
            if run is not None:
                run.status = "failed"
                run.error_class = type(exc).__name__
                run.finished_at = datetime.now(UTC)
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        stack.close()
        db.close()


def attach_to_thesis_run(db: Session, run_id: int, ticker: str, thesis_version_id: int | None) -> dict:
    """Paso posterior a una tesis generada: propuesta SOTP enlazada a esa versión. Nunca lanza.

    La tesis ya está confirmada cuando esto corre: un fallo aquí solo deja
    «sin propuesta de los agentes» y su motivo en ``result_payload.sotp_agents``.
    """
    from dramatiq.middleware.time_limit import TimeLimitExceeded

    from app.core.config import get_settings
    from app.services.company_resolver import resolve_company
    from app.services.expert_team.sotp_valuer import generate_sotp_proposal

    if not getattr(get_settings(), "thesis_sotp_agents_enabled", True):
        return {"status": "disabled"}
    tenant_id = db.info.get("tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0:
        # Modo legado sin tenant: no hay dónde guardar la propuesta; el run queda como estaba.
        return {"status": "no_tenant"}
    try:
        company = resolve_company(db, ticker)
        if company is None:
            outcome = {"status": "no_company"}
        else:
            outcome = generate_sotp_proposal(db, company, thesis_version_id=thesis_version_id,
                                             trigger="thesis").as_dict()
    except (Exception, TimeLimitExceeded) as exc:  # noqa: BLE001 - la tesis ya está publicada
        db.rollback()
        outcome = {"status": "error", "problems": [type(exc).__name__]}
    try:
        run = db.get(WorkflowRun, run_id)
        if run is not None:
            run.result_payload = {**(run.result_payload or {}), "sotp_agents": outcome}
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    return outcome


__all__ = ["WORKFLOW_NAME", "attach_to_thesis_run", "enqueue", "job_payload", "latest_run", "run_job"]
