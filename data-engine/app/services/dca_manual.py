"""Bounded manual DCA refresh; shared Redis gate, fail closed on outage."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import DcaEvaluationRun, DcaSignalState, MarketPrice
from app.services.dca_signal_engine import DEFAULT_PARAMS
from app.services.dca_signal_service import tracked_symbols

COOLDOWN_SECONDS = 300
MAX_SYMBOLS = 10
LEASE_SECONDS = 2100  # 30min actor limit + 5min shutdown/cleanup buffer
_RELEASE = "if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0"
_ACQUIRE = """
if redis.call('EXISTS',KEYS[1]) == 1 then return -1 end
local ttl=redis.call('TTL',KEYS[2])
if ttl > 0 then return ttl end
redis.call('SET',KEYS[1],ARGV[1],'EX',ARGV[2])
redis.call('SET',KEYS[2],ARGV[1],'EX',ARGV[3])
return 0
"""


def pending_symbols(db: Session, *, now: datetime | None = None) -> list[str]:
    """Never download to decide freshness; use stored state and known closes.

    A state is due if absent, older than 24h, parameter version changed or
    there is a newer stored market close. Failed symbols rotate behind ones
    not tried recently, so the first ten cannot starve the rest.
    """
    now = now or datetime.now(UTC)
    tracked = tracked_symbols(db)
    states = {s.symbol: s for s in db.scalars(select(DcaSignalState).where(*tenant_filters(db, DcaSignalState)))}
    # One aggregate for every tracked company (market_prices is shared market
    # data, not tenant-owned): a per-symbol query here was N+1 on the HTTP path.
    company_ids = {item.company.id for item in tracked.values() if item.company}
    newest_close = dict(db.execute(
        select(MarketPrice.company_id, func.max(MarketPrice.date))
        .where(MarketPrice.company_id.in_(company_ids))
        .group_by(MarketPrice.company_id)
    ).all()) if company_ids else {}
    candidates = []
    for symbol, item in tracked.items():
        state = states.get(symbol)
        newest = newest_close.get(item.company.id) if item.company else None
        evaluated = state.evaluated_at if state else None
        if evaluated and evaluated.tzinfo is None:
            evaluated = evaluated.replace(tzinfo=UTC)
        if state is None or state.params_version != DEFAULT_PARAMS.version or evaluated is None or now - evaluated >= timedelta(hours=24) or (newest and evaluated is not None and newest > evaluated.date()):
            candidates.append(symbol)
    # Retain bounded execution receipts as the durable retry order.
    attempted = {}
    for run in db.scalars(select(DcaEvaluationRun).where(
        DcaEvaluationRun.trigger == 'manual', *tenant_filters(db, DcaEvaluationRun))
        .order_by(DcaEvaluationRun.started_at.desc()).limit(60)):
        for symbol in (run.detail or {}).get('requested_symbols', []):
            attempted.setdefault(symbol, run.started_at.isoformat())
    return sorted(candidates, key=lambda s: (attempted.get(s, ''), s))


def acquire_manual_gate(client, tenant: str) -> tuple[str | None, int]:
    token = uuid.uuid4().hex
    # Same job-lease key as the daily worker, no manual-only lock.
    lock = f'cavaai:job-lease:evaluate_dca_signals:{tenant}'
    cooldown = f'cavaai:dca-manual-cooldown:{tenant}'
    status = int(client.eval(_ACQUIRE, 2, lock, cooldown, token, LEASE_SECONDS, COOLDOWN_SECONDS))
    return (token, 0) if status == 0 else (None, status)


def release_manual_gate(client, tenant: str, token: str) -> None:
    client.eval(_RELEASE, 1, f'cavaai:job-lease:evaluate_dca_signals:{tenant}', token)
