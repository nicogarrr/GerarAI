"""Admission is nonblocking and runs before any request DB session is opened."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException

import app.core.database as coredb
from app.core import db_admission as admission
from app.core.auth import get_research_principal


def principal(tenant):
    return SimpleNamespace(tenant_external_id=tenant, user_id="user", email=None)


def test_gate_tenant_isolation_global_cap_and_release():
    async def scenario():
        gate = admission.AdmissionGate(global_limit=3, tenant_limit=2)
        async with gate.slot("a"):
            async with gate.slot("a"):
                with pytest.raises(HTTPException) as exc:
                    async with gate.slot("a"):
                        pytest.fail("tenant cap bypassed")
                assert exc.value.status_code == 429
                async with gate.slot("b"):
                    with pytest.raises(HTTPException) as exc:
                        async with gate.slot("c"):
                            pytest.fail("global cap bypassed")
                    assert exc.value.status_code == 503
        assert gate.active == 0
        assert gate.tenants == {}
        async with gate.slot("a"):
            pass
    asyncio.run(scenario())


def test_gate_releases_cancelled_request():
    async def scenario():
        gate = admission.AdmissionGate(global_limit=1, tenant_limit=1)
        entered = asyncio.Event()
        async def request():
            async with gate.slot("a"):
                entered.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(request())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gate.active == 0
        assert gate.tenants == {}
    asyncio.run(scenario())


def test_fastapi_admission_precedes_db_and_health_is_independent(monkeypatch):
    gate = admission.AdmissionGate(global_limit=2, tenant_limit=1)
    monkeypatch.setattr(admission, "request_gate", lambda: gate)
    created = []
    class Session:
        info = {}
        def rollback(self): pass
        def close(self): pass
    def factory():
        created.append(True)
        return Session()
    monkeypatch.setattr(coredb, "SessionLocal", factory)
    monkeypatch.setattr(coredb, "settings", SimpleNamespace(research_auth_required=False, is_production=False))
    # Anonymous dev identity keeps this ordering test independent of SQL.
    app = FastAPI()
    app.dependency_overrides[get_research_principal] = lambda: None
    entered = asyncio.Event()
    done = asyncio.Event()
    @app.get("/api/read")
    async def read(db=Depends(coredb.get_db)):
        entered.set()
        await done.wait()
        return {"ok": True}
    @app.get("/health/ready")
    async def health():
        return {"ok": True}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = asyncio.create_task(client.get("/api/read"))
            await entered.wait()
            denied = await client.get("/api/read")
            assert denied.status_code == 429
            assert int(denied.headers["Retry-After"]) > 0
            assert len(created) == 1
            assert (await client.get("/health/ready")).status_code == 200
            done.set()
            assert (await first).status_code == 200
        assert gate.active == 0
    asyncio.run(scenario())


def test_real_get_db_declares_admission_before_its_body():
    import inspect
    dependency = inspect.signature(coredb.get_db).parameters["_admission"].default
    assert dependency.dependency is admission.admit_database_request


def test_request_gate_caps_pool_capacity_and_reuses_singleton(monkeypatch):
    monkeypatch.setattr(admission, "_GATE", None)
    monkeypatch.setattr(admission, "get_settings", lambda: SimpleNamespace(db_pool_size=30))
    gate = admission.request_gate()
    assert (gate.global_limit, gate.tenant_limit) == (16, 8)
    assert admission.request_gate() is gate
    monkeypatch.setattr(admission, "_GATE", None)
    monkeypatch.setattr(admission, "get_settings", lambda: SimpleNamespace(db_pool_size=1))
    assert admission.request_gate().global_limit == 1


def test_anonymous_dependency_releases_gate_after_error(monkeypatch):
    gate = admission.AdmissionGate(global_limit=2, tenant_limit=1)
    monkeypatch.setattr(admission, "request_gate", lambda: gate)

    async def scenario():
        dependency = admission.admit_database_request(principal=None)
        await anext(dependency)
        assert gate.tenants == {"anonymous": 1}
        await dependency.aclose()
        assert gate.tenants == {}
        assert gate.active == 0
    asyncio.run(scenario())
