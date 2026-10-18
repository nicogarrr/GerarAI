from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.auth import ResearchPrincipal, get_research_principal
from app.core.llm_tenant_scope import bind_llm_cache_tenant
from app.llm.response_cache import current_cache_tenant


def _app(principal):
    app = FastAPI()
    app.dependency_overrides[get_research_principal] = lambda: principal

    @app.get("/async", dependencies=[Depends(bind_llm_cache_tenant)])
    async def async_route():
        return {"tenant": current_cache_tenant()}

    @app.get("/sync", dependencies=[Depends(bind_llm_cache_tenant)])
    def sync_route():
        return {"tenant": current_cache_tenant()}

    return app


def test_verified_tenant_is_visible_to_async_and_sync_handlers():
    client = TestClient(_app(ResearchPrincipal(user_id="u1", tenant_external_id="tenant-a")))
    assert client.get("/async").json() == {"tenant": "tenant-a"}
    assert client.get("/sync").json() == {"tenant": "tenant-a"}
    # el scope no se filtra fuera del request
    assert current_cache_tenant() is None


def test_no_principal_means_no_tenant_scope():
    client = TestClient(_app(None))
    assert client.get("/async").json() == {"tenant": None}
