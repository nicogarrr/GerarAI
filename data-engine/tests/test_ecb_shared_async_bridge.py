"""The ECB sync adapter must use the shared context-propagating bridge."""

import asyncio
import contextvars
from datetime import date

import pytest

from app.services.connectors import ecb_history


@pytest.mark.parametrize("active_loop", [False, True])
def test_ecb_sync_adapter_preserves_context(monkeypatch, active_loop):
    tenant = contextvars.ContextVar("ecb_test_tenant", default=None)
    marker = object()
    day = date(2026, 10, 27)
    calls = []

    async def backfill(db, *, currencies, start, end, fetcher):
        assert db is marker
        assert tenant.get() == "tenant-synthetic"
        assert currencies == {"USD"}
        assert start == end == day
        calls.append(await fetcher(["USD"], start, end))
        return {"inserted": 1}

    monkeypatch.setattr(ecb_history, "backfill_ecb_rates", backfill)
    token = tenant.set("tenant-synthetic")
    try:
        def call():
            return ecb_history.backfill_ecb_rates_sync(
                marker, currencies={"USD"}, start=day, end=day,
                fetcher=lambda codes, start, end: "synthetic-csv",
            )

        async def scenario():
            return call()

        result = asyncio.run(scenario()) if active_loop else call()
        assert result == {"inserted": 1}
        assert calls == ["synthetic-csv"]
    finally:
        tenant.reset(token)
