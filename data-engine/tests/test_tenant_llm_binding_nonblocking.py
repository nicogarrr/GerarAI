"""Request binding must keep blocking tenant settings I/O off the event loop."""

import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.core.database import Base, get_db
from app.llm.tenant_config import (
    TenantLLMConfig,
    current_tenant_llm_config,
    tenant_llm_config_scope,
)
from app.models import Tenant, TenantLLMSettings
from app.services import tenant_llm_settings_service as service


def _config(model):
    return TenantLLMConfig(provider="openai", base_url="https://api.openai.com/v1", model=model)


def test_binding_does_not_block_loop_and_restores_parent_context(monkeypatch):
    """The loader needs an event-loop peer to finish; inline loading fails."""
    outer = _config("outer")
    loaded = _config("request")
    release = threading.Event()
    observed = []
    loop_thread = threading.get_ident()

    def load(db, tenant_id):
        observed.append((threading.get_ident(), tenant_id, current_tenant_llm_config()))
        assert release.wait(1), "loader blocked the event loop that must release it"
        return loaded

    monkeypatch.setattr(service, "load_config_for_tenant", load)

    async def run():
        async def peer():
            await asyncio.sleep(0)
            release.set()

        peer_task = asyncio.create_task(peer())
        gen = service.bind_tenant_llm_settings(SimpleNamespace(info={"tenant_id": 17}))
        try:
            await anext(gen)
            assert current_tenant_llm_config() is loaded
        finally:
            await gen.aclose()
            await peer_task
        assert current_tenant_llm_config() is outer

    with tenant_llm_config_scope(outer):
        asyncio.run(run())
    assert observed == [(observed[0][0], 17, None)]
    assert observed[0][0] != loop_thread


def test_http_concurrent_bindings_read_real_rows_off_loop_and_keep_tenants(tmp_path):
    """Actual ORM SELECT and config parsing, separate sessions per request."""
    engine = create_engine(f"sqlite:///{tmp_path / 'bindings.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Tenant(id=i, external_id=f"synthetic-{i}", name="synthetic") for i in (1, 2)])
        db.flush()
        db.add_all([
            TenantLLMSettings(tenant_id=i, provider="openai", model=f"model-{i}", enabled=False)
            for i in (1, 2)
        ])
        db.commit()
    observed_threads = []
    loop_thread = threading.get_ident()

    @event.listens_for(engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):
        if "FROM tenant_llm_settings" in statement:
            observed_threads.append(threading.get_ident())

    def scoped_db(request: Request):
        with Session(engine) as db:
            db.info["tenant_id"] = int(request.headers["x-synthetic-tenant"])
            yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = scoped_db

    @app.get("/bound", dependencies=[Depends(service.bind_tenant_llm_settings)])
    async def bound():
        config = current_tenant_llm_config()
        await asyncio.sleep(0)
        assert current_tenant_llm_config() is config
        return {"model": config.model, "enabled": config.enabled}

    async def run():
        outer = _config("parent")
        with tenant_llm_config_scope(outer):
            async with AsyncClient(transport=ASGITransport(app), base_url="http://isolated") as client:
                responses = await asyncio.gather(*[
                    client.get("/bound", headers={"x-synthetic-tenant": str(i)}) for i in (1, 2, 1, 2)
                ])
            assert current_tenant_llm_config() is outer
        assert [response.status_code for response in responses] == [200] * 4
        assert [response.json() for response in responses] == [
            {"model": f"model-{i}", "enabled": False} for i in (1, 2, 1, 2)
        ]

    try:
        asyncio.run(run())
        assert len(observed_threads) == 4
        assert all(thread != loop_thread for thread in observed_threads)
    finally:
        engine.dispose()


def test_binding_loader_error_restores_parent(monkeypatch):
    outer = _config("parent")

    def load(*args):
        raise RuntimeError("synthetic read failure")

    monkeypatch.setattr(service, "load_config_for_tenant", load)

    async def run():
        gen = service.bind_tenant_llm_settings(SimpleNamespace(info={"tenant_id": 17}))
        with pytest.raises(RuntimeError, match="synthetic read failure"):
            await anext(gen)
        assert current_tenant_llm_config() is outer
        await gen.aclose()

    with tenant_llm_config_scope(outer):
        asyncio.run(run())


def test_binding_without_tenant_clears_inherited_config_without_read(monkeypatch):
    outer = _config("parent")

    def unexpected(*args):
        pytest.fail("unscoped binding must not read tenant settings")

    monkeypatch.setattr(service, "load_config_for_tenant", unexpected)

    async def run():
        gen = service.bind_tenant_llm_settings(SimpleNamespace(info={}))
        await anext(gen)
        try:
            assert current_tenant_llm_config() is None
        finally:
            await gen.aclose()
        assert current_tenant_llm_config() is outer

    with tenant_llm_config_scope(outer):
        asyncio.run(run())
