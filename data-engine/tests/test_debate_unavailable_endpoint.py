"""Endpoint returns public 503 without persisting unavailable or invalid debates."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.thesis import router
from app.models import ThesisVersion

app = FastAPI()
app.include_router(router, prefix="/api/thesis")
from app.core.database import init_db
from app.llm.free_interactive import FreeLLMUnavailable


def _draft_thesis() -> ThesisVersion:
    # Una ThesisVersion real (no un SimpleNamespace): la puerta de publicación
    # lee tenant_id/company_id/status. Borrador sin modelo posterior: vigente.
    return ThesisVersion(id=None, tenant_id=None, company_id=None, version=1, status="draft",
                         thesis_markdown="tesis", executive_summary="")


def test_quota_exhausted_is_503_not_200(monkeypatch):
    init_db()
    monkeypatch.setattr("app.api.routes.thesis.ThesisService.latest", lambda *a: _draft_thesis())
    monkeypatch.setattr("app.api.routes.thesis.resolve_company", lambda *a: SimpleNamespace(id=None, ticker="EXEL"))
    seen = []
    monkeypatch.setattr("app.llm.free_interactive.create_free_interactive_provider", lambda: object())
    async def unavailable(*a, **kw):
        seen.append(kw)
        raise FreeLLMUnavailable(quota=True)
    monkeypatch.setattr("app.services.thesis_debate_service.debate_thesis", unavailable)
    response = TestClient(app).post("/api/thesis/EXEL/debate")
    assert response.status_code == 503
    assert response.json() == {
        "detail": "El modelo configurado ha agotado su cuota, vuelve más tarde"
    }
    assert seen[0]["strict_provider"] is True
    assert seen[0]["use_jev"] is False


def test_invalid_result_is_503_with_distinct_public_reason(monkeypatch):
    init_db()
    monkeypatch.setattr("app.api.routes.thesis.ThesisService.latest", lambda *a: _draft_thesis())
    monkeypatch.setattr("app.api.routes.thesis.resolve_company", lambda *a: SimpleNamespace(id=None, ticker="EXEL"))
    monkeypatch.setattr("app.llm.free_interactive.create_free_interactive_provider", lambda: object())
    async def invalid(*a, **kw):
        raise ValueError("provider-private-body")
    monkeypatch.setattr("app.services.thesis_debate_service.debate_thesis", invalid)
    response = TestClient(app).post("/api/thesis/EXEL/debate")
    assert response.status_code == 503
    assert response.json() == {"detail": "El debate devolvió una respuesta no válida; vuelve más tarde"}
