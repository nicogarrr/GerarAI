"""Durable manual DCA receipt and worker execution. No HTTP-lived evaluation."""
from __future__ import annotations

import redis
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.redis_retry import no_retry
from app.core.tenancy import tenant_filters
from app.models import DcaEvaluationRun
from app.services import dca_manual, dca_run_log


def redis_client():
    return redis.Redis.from_url(get_settings().redis_url,
        socket_connect_timeout=1, socket_timeout=2, retry=no_retry())


def run_manual_job(db, run_id: int, token: str) -> dict:
    """Only the accepted lease owner may run. No retry after ambiguous delivery."""
    from app.services.dca_signal_service import evaluate_watchlist
    tenant = str(db.info['tenant_id'])
    client = redis_client()
    row = None
    requested = []
    release = False
    try:
        row = db.scalar(select(DcaEvaluationRun).where(DcaEvaluationRun.id == run_id,
            *tenant_filters(db, DcaEvaluationRun)))
        if row is None or row.trigger != 'manual' or row.status != 'queued':
            return {'status': 'ignored'}
        key = f'cavaai:job-lease:evaluate_dca_signals:{tenant}'
        owner = client.get(key)
        if owner != token.encode():
            raise RuntimeError('La reserva de ejecución expiró antes de iniciar; vuelve a solicitarla.')
        # Compare-and-swap prevents duplicate broker delivery evaluating twice.
        claimed = db.execute(update(DcaEvaluationRun).where(DcaEvaluationRun.id == run_id,
            DcaEvaluationRun.status == 'queued', *tenant_filters(db, DcaEvaluationRun))
            .values(status='running')).rowcount
        db.commit()
        if claimed != 1:
            return {'status': 'ignored'}
        # The queue wait must not consume the worker's execution lease.
        renewed = client.eval(
            "if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('EXPIRE',KEYS[1],ARGV[2]) end return 0",
            1, key, token, dca_manual.LEASE_SECONDS)
        if not renewed:
            raise RuntimeError('No se pudo renovar la reserva de ejecución.')
        release = True
        row.status = 'running'
        requested = (row.detail or {}).get('requested_symbols', [])
        if len(requested) > dca_manual.MAX_SYMBOLS:
            raise ValueError('Manual DCA batch exceeds limit')
        remaining = (row.detail or {}).get('pending_remaining', 0)
        summary = evaluate_watchlist(db, symbols=set(requested))
        summary.update(requested=len(requested), pending_remaining=remaining,
            cooldown_seconds=dca_manual.COOLDOWN_SECONDS)
        # Summary first: finish_run commits status 'ok' together with it, so a
        # poll between two commits never sees 'ok' without a summary.
        row.detail = {**(row.detail or {}), 'requested_symbols': requested, 'summary': summary}
        dca_run_log.finish_run(db, row, summary=summary)
        return {'status': 'ok', 'run_id': run_id}
    except Exception as exc:
        db.rollback()
        if row is not None:
            requested = requested or (row.detail or {}).get('requested_symbols', [])
            dca_run_log.finish_run(db, row, error=f'{type(exc).__name__}: {exc}')
            row.detail = {**(row.detail or {}), 'requested_symbols': requested}
            db.commit()
        raise
    finally:
        try:
            if release:
                dca_manual.release_manual_gate(client, tenant, token)
        finally:
            client.close()
