"""Chat con el equipo de expertos para preguntas complejas, detrás de EXPERT_TEAM_ENABLED.

Apagado (defecto): el chat no llama al equipo y responde igual que antes.
Encendido: solo una pregunta sobre una empresa que pide ≥2 expertos
(«riesgo y valoración de X») pasa por el equipo; lo demás sigue por la
síntesis de siempre. LLM FALSO, sin red.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.llm import LLMResponse, Message, Usage
from app.models.entities import Base, Company, FinancialFact
from app.schemas.api import ChatResponse
from app.services import chat_service as chat_module
from app.services.chat_service import ChatService
from app.services.expert_team import chat as team_chat

COMPLEX = "¿Qué riesgo tiene CHAT y está cara su valoración? Mira también sus ingresos"
SIMPLE = "¿Qué riesgo tiene CHAT?"


class _FakeProvider:
    name = "fake"

    def __init__(self, *, cite: bool = True) -> None:
        self.cite = cite
        self.tasks: list[str] = []

    async def complete(self, request):
        task = dict(request.metadata).get("expert_team_task", "")
        self.tasks.append(task)
        payload = json.loads(request.messages[-1].content)
        ids = [ev["id"] for ev in payload.get("evidence", [])]
        claims = [{"text": "dato leído", "numbers": [], "citations": [i] if self.cite else []} for i in ids]
        body = json.dumps({"summary": "resumen", "stance": "neutral", "claims": claims})
        return LLMResponse(message=Message("assistant", body), usage=Usage(), model="fake", provider="fake")


SENTINEL = ChatResponse(answer="síntesis de siempre", sources=[], model="synthesis")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        company = Company(
            ticker="CHAT", name="Chat Co", exchange="NYSE", currency="USD", sector="S", industry="I",
            company_type="operating", valuation_model="dcf", special_sources=[], special_risks=[],
            factor_tags=[],
        )
        session.add(company)
        session.flush()
        for metric, value in (("revenue", 130), ("net_income", 20), ("free_cash_flow", 15)):
            session.add(FinancialFact(
                company_id=company.id, metric=metric, value=Decimal(value), unit="USD",
                period="FY2025", fiscal_year=2025, source_type="filing",
            ))
        session.commit()
        yield session


@pytest.fixture
def synthesis_calls(monkeypatch):
    calls: list[str] = []

    async def fake_synthesize(self, *, question, **kwargs):
        calls.append(question)
        return SENTINEL.model_copy()

    monkeypatch.setattr(chat_module.ChatSynthesisService, "synthesize", fake_synthesize)
    return calls


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("EXPERT_TEAM_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ask(db, question, provider, ticker="CHAT") -> ChatResponse:
    scope = "company" if ticker else "portfolio"
    return asyncio.run(ChatService(provider).answer(db, question, scope, ticker, use_jev=False))


def test_flag_off_never_calls_the_team(db, synthesis_calls, monkeypatch):
    async def boom(*args, **kwargs):  # pragma: no cover - no debe llamarse
        raise AssertionError("con el flag apagado el chat no llama al equipo")

    monkeypatch.setattr(team_chat, "run_team", boom)
    provider = _FakeProvider()
    response = _ask(db, COMPLEX, provider)
    assert response.answer == "síntesis de siempre"
    assert synthesis_calls == [COMPLEX]
    assert provider.tasks == []
    assert team_chat.wants_team(COMPLEX, "CHAT") is False


def test_flag_on_complex_question_uses_the_team(db, synthesis_calls, flag_on):
    provider = _FakeProvider()
    response = _ask(db, COMPLEX, provider)
    assert synthesis_calls == []
    assert response.model == "expert_team"
    trace = response.llm_trace["expert_team"]
    assert {"fundamental", "valuation", "risk"} <= set(trace["plan"])
    assert "tax" not in trace["plan"]  # sin posición, fiscal no entra
    assert response.sections and all(s.key in {"facts", "insufficient_data", "contradictions", "conclusion"}
                                      for s in response.sections)
    facts = [s for s in response.sections if s.key == "facts"]
    assert facts and facts[0].body.startswith("Fundamental")
    # cada fuente es un dato que una herramienta devolvió en esta corrida
    assert response.sources and all(src["table"] == "financial_facts" for src in response.sources
                                    if src["tool"] == "financial_facts")
    cited = {c for s in facts for c in s.citations}
    assert cited <= {src["id"] for src in response.sources}
    assert "**Fundamental**" in response.answer and "[ev-" not in response.answer and "[1]" in response.answer
    assert "financial_facts" not in "".join(src["title"] for src in response.sources)
    assert all(src["title"].startswith(f"[{src['n']}] ") for src in response.sources)


def test_brain_panel_shape_portfolio_scope_with_company_in_text(db, synthesis_calls, flag_on):
    # El Cerebro del layout envía scope="portfolio" y ticker=None: la empresa sale del texto.
    response = _ask(db, COMPLEX, _FakeProvider(), ticker=None)
    assert response.model == "expert_team"


def test_flag_on_simple_question_keeps_the_old_path(db, synthesis_calls, flag_on):
    provider = _FakeProvider()
    response = _ask(db, SIMPLE, provider)
    assert response.answer == "síntesis de siempre"
    assert provider.tasks == []


def test_no_valid_claim_falls_back_to_synthesis(db, synthesis_calls, flag_on):
    provider = _FakeProvider(cite=False)
    response = _ask(db, COMPLEX, provider)
    assert response.answer == "síntesis de siempre"
    assert synthesis_calls == [COMPLEX]


def test_team_failure_falls_back_to_synthesis(db, synthesis_calls, flag_on, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("caído")

    monkeypatch.setattr(team_chat, "run_team", broken)
    response = _ask(db, COMPLEX, _FakeProvider())
    assert response.answer == "síntesis de siempre"


def test_english_labels(db, synthesis_calls, flag_on, monkeypatch):
    monkeypatch.setattr(team_chat, "current_language", lambda: "en")
    provider = _FakeProvider()
    response = _ask(db, "What is the risk of CHAT and is its valuation expensive? Check revenue too", provider)
    assert response.model == "expert_team"
    facts = [s for s in response.sections if s.key == "facts"]
    assert facts[0].body.startswith("Fundamentals")
    assert "**Fundamentals**" in response.answer
    assert any(src["title"].startswith("[1] Financial statements") for src in response.sources)


def test_without_ticker_the_team_is_not_used(db, synthesis_calls, flag_on):
    assert team_chat.wants_team(COMPLEX, None) is False

