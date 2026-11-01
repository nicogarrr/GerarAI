"""Equipo de expertos en el catálogo de workflows, detrás de EXPERT_TEAM_ENABLED.

Flag apagado (defecto): el catálogo, el detalle y /run se comportan como antes
(la entrada no aparece y /run no ejecuta ni registra nada). Encendido: /run
ejecuta el equipo con un LLM FALSO (sin red) y guarda el resultado en el run.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

import main
from app.core.config import get_settings
from app.core.database import SessionLocal, init_db
from app.llm import LLMResponse, Message, Usage
from app.models import Company, WorkflowRun
from app.workflows.catalog import WORKFLOW_CATALOG, find_workflow
from tests.auth_helpers import csrf_client

client = csrf_client(main.app)
NAME = "ExpertTeamThesisWorkflow"


class _FakeProvider:
    def __init__(self) -> None:
        self.tasks: list[str] = []

    async def complete(self, request):
        self.tasks.append(dict(request.metadata).get("expert_team_task", ""))
        payload = json.loads(request.messages[-1].content)
        claims = [{"text": "dato leído", "numbers": [], "citations": [ev["id"]]} for ev in payload["evidence"]]
        body = json.dumps({"summary": "resumen", "stance": "neutral", "claims": claims})
        return LLMResponse(message=Message("assistant", body), usage=Usage(), model="fake", provider="fake")


def _seed(ticker: str) -> None:
    db = SessionLocal()
    try:
        if db.scalar(select(Company).where(Company.ticker == ticker)) is None:
            db.add(Company(ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD", sector="Tech",
                           industry="Tech", company_type="operating", valuation_model="dcf",
                           special_sources=[], special_risks=[], factor_tags=[]))
            db.commit()
    finally:
        db.close()


def _runs() -> int:
    db = SessionLocal()
    try:
        return len(db.scalars(select(WorkflowRun).where(WorkflowRun.workflow_name == NAME)).all())
    finally:
        db.close()


@pytest.fixture()
def flag_on(monkeypatch):
    monkeypatch.setenv("EXPERT_TEAM_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_entry_is_honest_and_flagged():
    entry = find_workflow(NAME)
    assert entry is not None and entry["feature_flag"] == "EXPERT_TEAM_ENABLED"
    assert entry["steps"] == ["plan_experts", "run_expert_team"]
    assert "EXPERT_TEAM_ENABLED" in entry["truth"] and "ThesisVersion" in entry["truth"]


def test_flag_off_listing_is_the_old_catalog():
    body = client.get("/api/workflows").json()
    names = [w["name"] for w in body["workflows"]]
    assert NAME not in names
    assert names == [w["name"] for w in WORKFLOW_CATALOG if not w.get("feature_flag")]


def test_flag_off_detail_and_run_execute_nothing():
    init_db()
    _seed("XTEAM")
    before = _runs()
    assert client.get(f"/api/workflows/{NAME}").status_code == 404
    response = client.post(f"/api/workflows/{NAME}/run", json={"ticker": "XTEAM"})
    assert response.status_code == 404
    assert "EXPERT_TEAM_ENABLED" in response.json()["detail"]
    assert _runs() == before


def test_flag_on_lists_and_runs_with_fake_llm(flag_on, monkeypatch):
    init_db()
    _seed("XTEAM")
    fake = _FakeProvider()
    monkeypatch.setattr("app.llm.factory.create_llm_provider", lambda *a, **k: fake)
    names = [w["name"] for w in client.get("/api/workflows").json()["workflows"]]
    assert NAME in names
    before = _runs()
    response = client.post(f"/api/workflows/{NAME}/run", json={"ticker": "xteam"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed" and body["ticker"] == "XTEAM"
    assert body["steps"] == ["plan_experts", "run_expert_team"]
    result = body["result"]
    assert result["plan"] == ["fundamental", "valuation", "risk", "news"]
    assert {r["expert"] for r in result["reports"]} == set(result["plan"])
    assert _runs() == before + 1


def test_flag_on_requires_ticker_and_known_company(flag_on):
    assert client.post(f"/api/workflows/{NAME}/run", json={}).status_code == 422
    assert client.post(f"/api/workflows/{NAME}/run", json={"ticker": "NOPE-ZZ"}).status_code == 404


def test_generate_thesis_entry_is_unchanged():
    entry = find_workflow("GenerateThesisWorkflow")
    assert entry is not None and entry["steps"] == ["generate_thesis"] and "feature_flag" not in entry
