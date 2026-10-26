import re
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

import main
from app.core.database import SessionLocal
from app.models import (
    CalculatedMetric,
    FundamentalModelVersion,
    MoatAssessment,
    ThesisNode,
    ValuationModel,
)
from app.seed import seed

DATA_ENGINE_ROOT = Path(__file__).resolve().parents[1]


def test_main_only_declares_root_and_health_routes():
    source = (DATA_ENGINE_ROOT / "main.py").read_text(encoding="utf-8")
    app_routes = re.findall(r"@app\.(?:get|post|put|patch|delete)\(\"([^\"]+)\"", source)

    assert "/" in app_routes
    assert "/health" in app_routes
    assert "/health/live" in app_routes
    assert "/health/ready" in app_routes
    assert "include_router(health_router, prefix=\"/api\")" in source
    # La API legacy (routers/) fue retirada: nada de fundamentals/market/analytics.
    assert "routers.analytics" not in source
    assert "routers.fundamentals" not in source
    assert "routers.market" not in source
    assert "knowledge_router" not in source
    assert "research_api_router," in source
    assert "dependencies=private_dependencies" in source
    assert "health_router" in source


def test_public_routes_are_registered_once():
    routes = list(main.app.openapi()["paths"].keys())

    expected_routes = {
            "/",
            "/health",
            "/health/live",
            "/health/ready",
            "/api/health",
            "/api/companies",
            "/api/companies/{ticker}",
        "/api/portfolio/summary",
        "/api/companies/{ticker}/metrics/calculated",
        "/api/companies/{ticker}/snapshot",
        "/api/companies/{ticker}/peers/comparison",
        "/api/portfolio/positions",
        "/api/portfolio/cash",
        "/api/portfolio/import/ibkr",
        "/api/portfolio/import/ibkr/xml",
        "/api/thesis/generate",
        "/api/thesis/{ticker}/latest",
        "/api/thesis/{ticker}/versions",
        "/api/valuation/{ticker}",
        "/api/news/manual",
        "/api/news",
        "/api/risk/dashboard",
        "/api/chat",
        "/api/sources/documents",
        "/api/sources/audits",
        "/api/sources/transcripts/import-text",
        "/api/settings",
        "/api/workflows",
    }

    for route in expected_routes:
        assert route in routes

    assert not any(route.startswith("/knowledge/") for route in routes)

    duplicates = {route for route in routes if routes.count(route) > 1}
    assert duplicates == set()


def test_root_and_health(monkeypatch):
    # La sonda LLM real requiere clave; aqui se aisla para probar el cableado.
    monkeypatch.setattr(main, "_probe_llm", lambda _settings: "ok")
    client = TestClient(main.app)

    assert client.get("/").json() == {"status": "ok", "service": "GerarAI Research Engine"}
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert "checks" in ready.json()
    assert "database" in ready.json()["checks"]
    assert ready.json()["checks"]["llm"] == "ok"


def test_health_ready_returns_503_when_database_is_down(monkeypatch):
    """/health/ready must not report HTTP 200 while degraded."""
    import app.core.database as database_module

    class FailingSession:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("database unreachable")

    monkeypatch.setattr(database_module, "SessionLocal", FailingSession)

    client = TestClient(main.app)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["database"].startswith("error:")


def test_company_workspace_uses_small_read_only_typed_snapshot_contract():
    seed()

    def mutable_row_counts() -> tuple[int, ...]:
        with SessionLocal() as db:
            return tuple(
                int(db.scalar(select(func.count()).select_from(model)) or 0)
                for model in (
                    CalculatedMetric,
                    FundamentalModelVersion,
                    MoatAssessment,
                    ThesisNode,
                    ValuationModel,
                )
            )

    before = mutable_row_counts()
    response = TestClient(main.app).get("/api/companies/MSFT/snapshot")
    after = mutable_row_counts()

    assert response.status_code == 200
    assert after == before
    payload = response.json()
    assert payload["company"]["ticker"] == "MSFT"
    assert {
        "latest_thesis",
        "valuation_summary",
        "model_summary",
        "research_health",
        "counts",
        "recent_changes",
    }.issubset(payload)
    assert "facts" not in payload
    assert "sourceDocuments" not in payload
    operation = main.app.openapi()["paths"]["/api/companies/{ticker}/snapshot"]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/CompanySnapshotOut")


def test_settings_exposes_llm_status_without_key_material():
    """GET /settings reports provider/model/configured, never the API key."""
    client = TestClient(main.app)
    response = client.get("/api/settings")
    assert response.status_code == 200
    llm = response.json()["llm"]
    assert llm["provider"] in {"opencode-go", "disabled"}
    assert isinstance(llm["configured"], bool)
    if llm["configured"]:
        assert llm["model"]
    else:
        assert llm["model"] is None
        assert llm["reason"]
    # The env var NAME may appear in the disabled reason; key material never does.
    assert "sk-" not in response.text


def test_settings_llm_configured_never_leaks_the_key(monkeypatch):
    from app.core.config import get_settings

    canary = "sk-live-canary-9f8e7d6c"
    monkeypatch.setattr(get_settings(), "opencode_go_api_key", canary)

    client = TestClient(main.app)
    response = client.get("/api/settings")
    assert response.status_code == 200
    llm = response.json()["llm"]
    assert llm["provider"] == "opencode-go"
    assert llm["configured"] is True
    assert llm["model"]
    assert canary not in response.text
    assert "api_key" not in response.text.lower()
