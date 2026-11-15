"""Bound request concurrency before synchronous DB dependencies reserve pool slots.

This is a process-local fail-fast admission gate, not a rate-limit replacement.
For pool sizes >=4 a tenant cannot occupy every admission slot. For
pool sizes 1/2/3 admission degrades to 1 global / 1 tenant, without a
reserve or cross-tenant isolation guarantee. Health probes do not
use get_db and remain outside the gate. Counters are released on cancellation.
"""
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, HTTPException

from app.core.auth import ResearchPrincipal, get_research_principal
from app.core.config import get_settings


class AdmissionGate:
    def __init__(self, global_limit: int, tenant_limit: int):
        self.global_limit = max(1, global_limit)
        self.tenant_limit = max(1, min(tenant_limit, self.global_limit))
        self.active = 0
        self.tenants: dict[str, int] = {}
        self._lock = threading.Lock()

    @asynccontextmanager
    async def slot(self, tenant: str):
        # Never wait for a DB connection or occupy an AnyIO worker thread.
        # A short lock also makes the singleton safe in multi-loop tests.
        with self._lock:
            count = self.tenants.get(tenant, 0)
            if count >= self.tenant_limit:
                raise HTTPException(429, "Too many concurrent tenant requests", headers={"Retry-After": "5"})
            if self.active >= self.global_limit:
                raise HTTPException(503, "Database request capacity busy", headers={"Retry-After": "5"})
            self.active += 1
            self.tenants[tenant] = count + 1
        try:
            yield
        finally:
            with self._lock:
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
