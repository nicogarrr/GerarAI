"""historical-stress: fallos de proveedor en cache corta y tope de tiempo total."""

import asyncio
import time

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base
from app.services import historical_stress_service as svc


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


@pytest.fixture(autouse=True)
def _reset():
    getattr(svc, "_FAILED_UNTIL", {}).clear()
    yield
    getattr(svc, "_FAILED_UNTIL", {}).clear()


def test_recent_provider_failure_is_not_retried_immediately(db, monkeypatch):
    calls = []

    async def boom(symbol):
        calls.append(symbol)
        raise httpx.ConnectError("down")

    monkeypatch.setattr(svc, "load_history", boom)
    first = asyncio.run(svc.HistoricalStressService().build(db, ticker="AAA"))
    second = asyncio.run(svc.HistoricalStressService().build(db, ticker="AAA"))
    assert len(calls) == 1
    assert first["companies"][0]["history_failure"] == "provider_error"
    assert second["companies"][0]["history_failure"] == "provider_error"


def test_total_time_budget_returns_partial_marked(db, monkeypatch):
    async def slow(symbol):
        await asyncio.sleep(5)
        return {}

    monkeypatch.setattr(svc, "load_history", slow)
    start = time.monotonic()
    result = asyncio.run(svc.HistoricalStressService().build(db, ticker="AAA", budget_seconds=0.3))
    assert time.monotonic() - start < 2
    assert result["companies"][0]["history_failure"] == "provider_error"
