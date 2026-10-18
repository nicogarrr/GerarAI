"""Bounded add-only analysis using the existing durable thesis outbox."""
from datetime import UTC, datetime

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import WorkflowRun
from app.services.thesis_job_service import (
    WORKFLOW_NAME,
    _lock_generation,
    enqueue_generation,
    latest_generation,
)

DAILY_LIMIT = 20


def enqueue_tracked_analysis(db: Session, ticker: str) -> None:
    tenant = db.info.get('tenant_id')
    if tenant is None or not db.info.get('user_id'):
        return
    now = datetime.now(UTC)
    # Serialize quota and enqueue across workers, including different tickers.
    _lock_generation(db, tenant, 'tracked-daily-quota', False)
    latest = latest_generation(db, ticker)
    if latest is not None:
        created = latest.created_at
        created = created.replace(tzinfo=UTC) if created.tzinfo is None else created.astimezone(UTC)
        if latest.status in {"queued", "running", "retrying", "dispatch_failed"} or created.date() == now.date():
            return
    count = db.scalar(select(func.count()).select_from(WorkflowRun).where(
        WorkflowRun.workflow_name == WORKFLOW_NAME,
        WorkflowRun.tenant_id == tenant,
        WorkflowRun.input_payload['tracked'].as_boolean().is_(True),
        WorkflowRun.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0),
    )) or 0
    if count >= DAILY_LIMIT:
        return
    enqueue_generation(db, ticker, request_id=f'tracked:{now.date()}', tracked=True)


def tracked_statuses(db: Session, tickers: list[str]) -> dict[str, dict]:
    if not tickers or db.info.get('tenant_id') is None:
        return {}
    rows = db.scalars(select(WorkflowRun).where(
        WorkflowRun.tenant_id == db.info['tenant_id'],
        WorkflowRun.workflow_name == WORKFLOW_NAME,
        WorkflowRun.input_payload['ticker'].as_string().in_(tickers),
    ).order_by(desc(WorkflowRun.id))).all()
    out = {}
    for run in rows:
        ticker = run.input_payload['ticker']
        if ticker not in out:
            out[ticker] = {
                'status': run.status,
                'as_of': (run.finished_at or run.started_at or run.created_at).isoformat(),
                'thesis_status': (run.result_payload or {}).get('status'),
            }
    return out
