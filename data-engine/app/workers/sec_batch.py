"""Small SEC batches; requests still go through the shared SEC client pacer."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from time import monotonic
from typing import TypeVar

BATCH_SIZE = 3
BUDGET_SECONDS = 60
POLL_TIMEOUT_SECONDS = 30
ACTOR_TIME_LIMIT_MS = 180_000
T = TypeVar("T")


async def bounded_poll(poll: Awaitable[T]) -> T:
    # Includes network retries and pacing waits. Cancellation never bypasses
    # SECClient's shared Redis pacer or its Retry-After cooldown.
    return await asyncio.wait_for(poll, timeout=POLL_TIMEOUT_SECONDS)


class SecBatch:
    def __init__(self, companies, start_after: str | None = None):
        self.companies = sorted(
            (c for c in companies if c.cik and (start_after is None or c.ticker > start_after)),
            key=lambda c: c.ticker,
        )
        self.started = monotonic()
        self.completed = 0
        self.cursor = start_after

    def can_start(self) -> bool:
        return self.completed < BATCH_SIZE and (
            self.completed == 0 or monotonic() - self.started < BUDGET_SECONDS
        )

    def checkpoint(self, ticker: str) -> None:
        self.cursor = ticker
        self.completed += 1

    @property
    def has_more(self) -> bool:
        return self.completed < len(self.companies)
