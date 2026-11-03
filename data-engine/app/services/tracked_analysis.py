"""Bounded add-only analysis using the existing durable thesis outbox."""
from datetime import UTC, datetime

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, aliased

from app.models import WatchItem, WorkflowRun
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
    # Solo importa la ÚLTIMA corrida de cada ticker, pero antes se hidrataban
    # TODAS las corridas históricas de esos tickers (con result_payload entero)
    # y se descartaban en Python. Ventana row_number (portable sqlite/PG, mismo
    # patrón que company_snapshot_service): la BD devuelve una fila por ticker.
    # Medido en lab con 178k corridas y 12 tickers (índice 0123 aplicado):
    # 5,4 ms -> 1,9 ms; sin índice la consulta anterior costaba 40,4 ms.
    ticker_expr = WorkflowRun.input_payload['ticker'].as_string()
    ranked = select(
        WorkflowRun,
        func.row_number().over(partition_by=ticker_expr, order_by=desc(WorkflowRun.id)).label("rank_"),
    ).where(
        WorkflowRun.tenant_id == db.info['tenant_id'],
        WorkflowRun.workflow_name == WORKFLOW_NAME,
        ticker_expr.in_(tickers),
    ).subquery()
    aliased_run = aliased(WorkflowRun, ranked)
    rows = db.scalars(select(aliased_run).where(ranked.c.rank_ == 1)).all()
    out = {}
    for run in rows:
        ticker = run.input_payload['ticker']
        if ticker not in out:
            out[ticker] = {
                'status': run.status,
                'as_of': (run.finished_at or run.started_at or run.created_at).isoformat(),
                'thesis_status': (run.result_payload or {}).get('status'),
            }
    # Motivo del «faltan datos»: los inputs pendientes del último modelo
    # fundamental persistido (QA Tester 6, 19-oct-2026: la watchlist decía
    # «Análisis: faltan datos» sin explicar qué falta).
    insufficient = [t for t, state in out.items()
                    if state.get('thesis_status') == 'insufficient_data']
    if insufficient:
        from app.models import Company
        from app.services.thesis_service import latest_missing_inputs
        company_ids = {
            c.ticker: c.id
            for c in db.scalars(
                select(Company).where(Company.ticker.in_(insufficient))).all()
        }
        for ticker in insufficient:
            company_id = company_ids.get(ticker)
            if company_id is not None:
                out[ticker]['missing_inputs'] = latest_missing_inputs(db, company_id)
    return out


# Una empresa de la watchlist cuya ultima tesis quedo en «datos insuficientes»
# se reintenta como mucho una vez cada este numero de dias: los huecos se
# cierran con ingestas nuevas (fundamentales, Yahoo en modo huecos), no por
# reintentar cada hora.
RETRY_INSUFFICIENT_DAYS = 3


def backfill_watchlist_theses(db: Session, *, limit: int = DAILY_LIMIT) -> dict:
    """Tesis en segundo plano para la watchlist del tenant activo (owner 3-nov-2026:
    «toda empresa que entre en watchlist se genere la tesis en segundo plano»).

    El alta ya encola la tesis; esto cubre lo que el alta no garantiza: empresas
    añadidas antes de existir esa generación, corridas fallidas y tesis que
    salieron «datos insuficientes» cuando faltaba un dato que ya puede estar.
    Reutiliza ``enqueue_tracked_analysis`` (dedupe por día, tope diario por
    tenant, nunca dos generaciones activas del mismo ticker).
    """
    from app.models import Company, ThesisVersion

    if db.info.get("tenant_id") is None:
        return {"status": "skipped", "reason": "sin tenant"}
    tenant = db.info["tenant_id"]
    symbols = [
        item.symbol
        for item in db.scalars(
            select(WatchItem).where(WatchItem.tenant_id == tenant).order_by(WatchItem.id)
        ).all()
    ]
    if not symbols:
        return {"status": "ok", "enqueued": [], "skipped": {}}
    now = datetime.now(UTC)
    companies = {
        c.ticker: c.id for c in db.scalars(select(Company).where(Company.ticker.in_(symbols))).all()
    }
    ranked = select(
        ThesisVersion.company_id,
        ThesisVersion.status,
        ThesisVersion.created_at,
        func.row_number().over(
            partition_by=ThesisVersion.company_id, order_by=desc(ThesisVersion.version)
        ).label("rank_"),
    ).where(
        ThesisVersion.tenant_id == tenant,
        ThesisVersion.company_id.in_(list(companies.values()) or [-1]),
    ).subquery()
    latest = {
        row.company_id: (row.status, row.created_at)
        for row in db.execute(select(ranked).where(ranked.c.rank_ == 1)).all()
    }
    enqueued: list[str] = []
    skipped: dict[str, str] = {}
    for symbol in symbols:
        if len(enqueued) >= limit:
            skipped[symbol] = "tope_diario"
            continue
        company_id = companies.get(symbol)
        state = latest.get(company_id) if company_id is not None else None
        if state is not None:
            status, created = state
            created = created.replace(tzinfo=UTC) if created.tzinfo is None else created.astimezone(UTC)
            if status != "insufficient_data":
                skipped[symbol] = f"tesis_{status}"
                continue
            if (now - created).days < RETRY_INSUFFICIENT_DAYS:
                skipped[symbol] = "insuficiente_reciente"
                continue
        run = latest_generation(db, symbol, active_only=True)
        if run is not None:
            skipped[symbol] = "en_curso"
            continue
        before = latest_generation(db, symbol)
        enqueue_tracked_analysis(db, symbol)
        after = latest_generation(db, symbol)
        if after is not None and (before is None or after.id != before.id or after.status in {"queued"}):
            enqueued.append(symbol)
        else:
            skipped[symbol] = "deduplicado"
    return {"status": "ok", "enqueued": enqueued, "skipped": skipped}
