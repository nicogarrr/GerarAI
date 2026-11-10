"""A blocking monitor query must not stall unrelated async navigation reads."""

import asyncio
import threading
from datetime import date, timedelta

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes import watchlist
from app.core.database import Base, get_db
from app.core.i18n import current_language
from app.models import Company, FundamentalModelVersion, MarketPrice, Tenant, ThesisVersion


@pytest.fixture
def monitor_app(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'monitor.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Tenant(id=i, external_id=f"monitor-{i}", name="synthetic") for i in (1, 2)])
        company = Company(ticker="LOOPTEST", name="Loop test", exchange="NYSE", currency="USD",
                          company_type="listed", valuation_model="dcf")
        db.add(company)
        db.flush()
        for days, close in ((20, 80), (1, 100), (0, 110)):
            db.add(MarketPrice(company_id=company.id, date=date.today() - timedelta(days=days), close=close))
        for tenant_id, value in ((1, 150), (2, 75)):
            db.add(FundamentalModelVersion(
                tenant_id=tenant_id, company_id=company.id, version=tenant_id,
                engine_version="test", algorithm_version="test", framework_key="dcf",
                horizon_years=10, status="ok", publishable=True,
                input_fingerprint="input", forecast_fingerprint="forecast",
                market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation",
            ))
            db.add(ThesisVersion(tenant_id=tenant_id, company_id=company.id, version=tenant_id,
                                 status="published", expected_value=value,
                                 thesis_markdown="synthetic", executive_summary="synthetic"))
        db.commit()

    def scoped_db(request: Request):
        with Session(engine) as db:
            db.info.update(tenant_id=int(request.headers.get("x-synthetic-tenant", "1")), user_id="synthetic")
            yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = scoped_db
    app.include_router(watchlist.router, prefix="/api/watchlist")

    @app.get("/")
    async def root():
        return {"ok": True}

    try:
        yield app, engine
    finally:
        engine.dispose()


def test_monitor_sql_can_wait_for_event_loop_peer_without_freezing_root(monitor_app):
    """Actual SQL cursor waits; the loop must serve eight peer requests to release it."""
    app, engine = monitor_app
    started, release = threading.Event(), threading.Event()
    loop_thread = threading.get_ident()
    observed = []

    @event.listens_for(engine, "before_cursor_execute")
    def block_monitor_query(conn, cursor, statement, parameters, context, executemany):
        if "FROM companies" in statement:
            observed.append((threading.get_ident(), current_language()))
            started.set()
            assert release.wait(1), "monitor query froze the event loop needed to release it"

    async def run():
        async with AsyncClient(transport=ASGITransport(app), base_url="http://isolated") as client:
            monitor_task = asyncio.create_task(client.get("/api/watchlist/monitor?tickers=LOOPTEST"))
            try:
                while not started.is_set() and not monitor_task.done():
                    await asyncio.sleep(0)
                roots = await asyncio.gather(*(client.get("/") for _ in range(8)))
                assert all(response.json() == {"ok": True} for response in roots)
            finally:
                release.set()
            response = await monitor_task
            assert response.status_code == 200
            item = response.json()["items"]["LOOPTEST"]
            assert item["last_close"] == 110
            assert item["low_52w"] == 80
            assert item["low_52w_sessions"] == 3
            assert response.json()["earnings_status"] == "stored"

    asyncio.run(run())
    assert observed
    assert all(thread != loop_thread for thread, _ in observed)
    assert all(language == "es" for _, language in observed)


def test_monitor_orm_reads_run_off_loop_and_preserve_two_tenant_results(monitor_app):
    app, engine = monitor_app
    loop_thread = threading.get_ident()
    threads = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            threads.append(threading.get_ident())

    async def run():
        async with AsyncClient(transport=ASGITransport(app), base_url="http://isolated") as client:
            responses = await asyncio.gather(*[
                client.get("/api/watchlist/monitor?tickers=LOOPTEST", headers={"x-synthetic-tenant": str(i)})
                for i in (1, 2, 1, 2)
            ])
        assert [response.status_code for response in responses] == [200] * 4
        items = [response.json()["items"]["LOOPTEST"] for response in responses]
        assert [item["fair_value"] for item in items] == [150, 75, 150, 75]
        assert all(item["last_close"] == 110 for item in items)

    asyncio.run(run())
    assert threads
    assert all(thread != loop_thread for thread in threads)
