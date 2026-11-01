"""Bounded, resumable radar coordinator, without alerts or LLM side effects."""
from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any


class ProviderThrottled(Exception):
    """Provider rejected further traffic; caller resumes in a later batch."""


@dataclass(frozen=True)
class ScanBudget:
    max_companies: int = 1000
    max_seconds: float = 1800
    min_request_interval: float = 1.0

    def __post_init__(self):
        if not 1 <= self.max_companies <= 1000:
            raise ValueError('max_companies must be 1..1000')
        if not math.isfinite(self.max_seconds) or not 0 < self.max_seconds <= 1800:
            raise ValueError('max_seconds must be 0..1800')
        if not math.isfinite(self.min_request_interval) or self.min_request_interval < 1:
            raise ValueError('minimum request interval is one second')


def scan_batch(
    company_ids: Sequence[int], *, after_id: int = 0,
    fetch_and_evaluate: Callable[[int], dict[str, Any]],
    save_and_checkpoint: Callable[[int, dict[str, Any]], None],
    budget: ScanBudget = ScanBudget(),
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Checkpoint only after a durable save; a failing item never advances cursor.

    The data adapter must set its own network timeout. A bounded batch cannot
    interrupt an in-flight provider call. Rate limits stop the batch immediately,
    never retrying aggressively. One invocation owns one distributed scan lease.
    """
    targets = sorted({i for i in company_ids if i > after_id})
    start = clock()
    previous_request = None
    cursor = after_id
    saved = 0
    status = 'completed'
    for company_id in targets:
        if saved >= budget.max_companies:
            status = 'company_budget'
            break
        elapsed = clock() - start
        if elapsed >= budget.max_seconds:
            status = 'time_budget'
            break
        if previous_request is not None:
            delay = max(0.0, budget.min_request_interval - (clock() - previous_request))
            if clock() - start + delay >= budget.max_seconds:
                status = 'time_budget'
                break
            if delay:
                sleep(delay)
        previous_request = clock()
        try:
            result = fetch_and_evaluate(company_id)
        except ProviderThrottled:
            status = 'provider_throttled'
            break
        # Save failure propagates, so a rollback cannot produce a false cursor.
        save_and_checkpoint(company_id, result)
        cursor = company_id
        saved += 1
    return {'status': status, 'cursor': cursor, 'saved': saved,
            'remaining': sum(i > cursor for i in targets),
            'duration_seconds': clock() - start}
