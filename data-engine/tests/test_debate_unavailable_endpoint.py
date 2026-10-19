"""Endpoint returns public 503 without persisting unavailable or invalid debates."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.thesis import router

app = FastAPI()
app.include_router(router, prefix="/api/thesis")
from app.core.database import init_db
from app.llm.free_interactive import FreeLLMUnavailable


def test_quota_exhausted_is_503_not_200(monkeypatch):
    init_db()
    monkeypatch.setattr("app.api.routes.thesis.ThesisService.latest", lambda *a: SimpleNamespace(id=None, thesis_markdown="tesis", executive_summary=""))
    monkeypatch.setattr("app.api.routes.thesis.resolve_company", lambda *a: SimpleNamespace(id=None, ticker="EXEL"))
    seen = []
    monkeypatch.setattr("app.llm.free_interactive.create_free_interactive_provider", lambda: object())
    async def unavailable(*a, **kw):
        seen.append(kw)
        raise FreeLLMUnavailable(quota=True)
    monkeypatch.setattr("app.services.thesis_debate_service.debate_thesis", unavailable)
    response = TestClient(app).post("/api/thesis/EXEL/debate")
    assert response.status_code == 503
    assert response.json() == {"detail": "LLM gratuito agotado, vuelve más tarde"}
    assert seen[0]["strict_provider"] is True
    assert seen[0]["use_jev"] is False


def test_invalid_result_is_503_with_distinct_public_reason(monkeypatch):
    init_db()
    monkeypatch.setattr("app.api.routes.thesis.ThesisService.latest", lambda *a: SimpleNamespace(id=None, thesis_markdown="tesis", executive_summary=""))
    monkeypatch.setattr("app.api.routes.thesis.resolve_company", lambda *a: SimpleNamespace(id=None, ticker="EXEL"))
    monkeypatch.setattr("app.llm.free_interactive.create_free_interactive_provider", lambda: object())
    async def invalid(*a, **kw):
        raise ValueError("provider-private-body")
    monkeypatch.setattr("app.services.thesis_debate_service.debate_thesis", invalid)
    response = TestClient(app).post("/api/thesis/EXEL/debate")
    assert response.status_code == 503
    assert response.json() == {"detail": "El debate devolvió una respuesta no válida; vuelve más tarde"}
