"""Bound request concurrency before synchronous DB dependencies reserve pool slots.

This is a process-local bounded admission queue, not a rate-limit replacement.
For pool sizes >=4 a tenant cannot occupy every admission slot. For
pool sizes 1/2/3 admission degrades to 1 global / 1 tenant, without a
reserve or cross-tenant isolation guarantee. Health probes do not
use get_db and remain outside the gate. Counters are released on cancellation.
"""
import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import Depends, HTTPException

from app.core.auth import ResearchPrincipal, get_research_principal
from app.core.config import get_settings


class AdmissionGate:
    def __init__(self, global_limit: int, tenant_limit: int, *, wait_seconds: float = 1.0,
                 max_pending: int = 32, max_pending_per_tenant: int = 16):
        self.global_limit = max(1, global_limit)
        self.tenant_limit = max(1, min(tenant_limit, self.global_limit))
        self.wait_seconds = max(0.0, wait_seconds)
        self.max_pending = max(0, max_pending)
        self.max_pending_per_tenant = max(0, max_pending_per_tenant)
        self.active = 0
        self.tenants: dict[str, int] = {}
        self._waiting: list[tuple[object, str]] = []
        self._lock = threading.Lock()

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._waiting)

    def _eligible(self, tenant: str) -> bool:
        return self.active < self.global_limit and self.tenants.get(tenant, 0) < self.tenant_limit

    def _first_eligible(self) -> object | None:
        # Oldest ELIGIBLE waiter wins. A tenant at its active cap cannot block
        # another tenant's reserved capacity; same-tenant arrivals stay FIFO.
        return next((token for token, tenant in self._waiting if self._eligible(tenant)), None)

    def _busy(self, tenant: str) -> HTTPException:
        if self.tenants.get(tenant, 0) >= self.tenant_limit or self.active < self.global_limit:
            return HTTPException(429, "Too many concurrent tenant requests", headers={"Retry-After": "1"})
        return HTTPException(503, "Database request capacity busy", headers={"Retry-After": "1"})

    @asynccontextmanager
    async def slot(self, tenant: str):
        token = object()
        deadline = time.monotonic() + self.wait_seconds
        acquired = False
        queued = False
        try:
            while not acquired:
                with self._lock:
                    if queued and time.monotonic() >= deadline:
                        raise self._busy(tenant)
                    first = self._first_eligible()
                    if self._eligible(tenant) and (first is None or first is token):
                        if queued:
                            self._waiting.remove((token, tenant))
                            queued = False
                        self.active += 1
                        self.tenants[tenant] = self.tenants.get(tenant, 0) + 1
                        acquired = True
                    elif time.monotonic() >= deadline:
                        raise self._busy(tenant)
                    elif not queued:
                        tenant_pending = sum(1 for _, owner in self._waiting if owner == tenant)
                        if len(self._waiting) >= self.max_pending or tenant_pending >= self.max_pending_per_tenant:
                            raise self._busy(tenant)
                        self._waiting.append((token, tenant))
                        queued = True
                if not acquired:
                    # Await before get_db: no connection/session and no AnyIO
                    # worker thread is held. Short polling also keeps this
                    # process-local gate safe across multiple event loops.
                    await asyncio.sleep(min(0.005, max(0.0, deadline - time.monotonic())))
            yield
        finally:
            with self._lock:
                if queued:
                    self._waiting.remove((token, tenant))
                if acquired:
                    self.active -= 1
                    left = self.tenants[tenant] - 1
                    if left:
                        self.tenants[tenant] = left
                    else:
                        del self.tenants[tenant]


_GATE: AdmissionGate | None = None
_GATE_LOCK = threading.Lock()


def request_gate() -> AdmissionGate:
    global _GATE
    with _GATE_LOCK:
        if _GATE is None:
            settings = get_settings()
            # With pool>=4 leave two normal slots for readiness/background.
            # Tiny pools stay usable best-effort; no reserve is promised.
            # Overflow is never counted as request capacity.
            if settings.db_pool_size < 4:
                logging.getLogger(__name__).warning(
                    "DB pool size %s: best-effort admission 1/1; no guaranteed "
                    "connection reserve or cross-tenant isolation", settings.db_pool_size,
                )
            limit = max(1, min(16, settings.db_pool_size - 2))
            _GATE = AdmissionGate(limit, min(8, max(1, limit // 2)))
        return _GATE


async def admit_database_request(
    principal: ResearchPrincipal | None = Depends(get_research_principal),
):
    # Anonymous test/dev requests share one bounded bucket. Production auth
    # remains fail-closed in get_research_principal/get_db.
    tenant = principal.tenant_external_id if principal is not None else "anonymous"
    async with request_gate().slot(tenant):
        yield
