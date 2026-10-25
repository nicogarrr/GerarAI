"""ChatSynthesisService contracts: citation verification and honest fallback.

The LLM layer sits on top of a deterministic chat contract. The load-bearing
honesty rules: citations must point at sources that were actually retrieved,
grounded sections may not drop the citations the baseline carried, and any
failure must fall back to the deterministic answer - never to an
unverifiable LLM answer presented as grounded.
"""

import asyncio
import json

from app.llm import LLMResponse, Message
from app.llm.contracts import Usage
from app.schemas import ChatResponse, SynthesisSection
from app.services.chat_synthesis_service import SECTION_ORDER, ChatSynthesisService


class StubProvider:
    name = "stub"

    def __init__(self, payload: dict | None = None, error: Exception | None = None):
        self.payload = payload
        self.error = error

    async def complete(self, request):
        if self.error is not None:
            raise self.error
        return LLMResponse(
            message=Message("assistant", json.dumps(self.payload)),
            usage=Usage(input_tokens=100, output_tokens=50, total_tokens=150),
            model="stub-model",
            provider="stub",
            request_id="req-1",
        )


def _baseline(with_facts: bool = True) -> ChatResponse:
    grounded = {"facts", "calculations"} if with_facts else set()
    sections = [
        SynthesisSection(
            key=key,
            body=f"baseline {key}",
            citations=["financial_fact:1"] if key in grounded else [],
        )
        for key in SECTION_ORDER
    ]
    sources = [{"type": "financial_fact", "id": 1}] if with_facts else []
    return ChatResponse(answer="baseline answer", sections=sections, sources=sources)


def _llm_payload(citations=None, drop_facts_citations: bool = False, skip_key: str | None = None):
    citations = ["financial_fact:1"] if citations is None else citations
    sections = []
    for key in SECTION_ORDER:
        if key == skip_key:
            continue
        section_citations = [] if (drop_facts_citations and key == "facts") else citations
        sections.append({"key": key, "body": f"llm {key}", "citations": section_citations})
    return {
        "sections": sections,
        "confidence": 0.8,
        "insufficient_data": False,
        "answer": "Respuesta natural en prosa, breve y en castellano.",
    }



def test_valid_synthesis_replaces_sections_and_records_trace():
    provider = StubProvider(payload=_llm_payload())
    result = asyncio.run(ChatSynthesisService(provider).synthesize(
        question="q", ticker="AAA", baseline=_baseline()
    ))
    assert result.model == "stub-model"
    assert result.confidence == 0.8
    assert result.prompt_version
    assert result.answer == "Respuesta natural en prosa, breve y en castellano."
    assert "HECHO" not in result.answer
    assert result.llm_trace["json_validity"] is True
    assert result.llm_trace["citation_verification"] is True
    assert result.llm_trace["request_id"] == "req-1"



def test_unknown_citation_falls_back_to_deterministic():
    provider = StubProvider(payload=_llm_payload(citations=["financial_fact:999"]))
    baseline = _baseline()
    result = asyncio.run(ChatSynthesisService(provider).synthesize(
        question="q", ticker="AAA", baseline=baseline
    ))
    assert result.model == "deterministic"
    assert result.llm_trace["fallback"] is True
    assert result.llm_trace["fallback_reason"] == "ValueError"
    assert result.llm_trace["citation_verification"] is False
    assert result.sections[0].body == "baseline facts"



def test_grounded_section_cannot_drop_baseline_citations():
    provider = StubProvider(payload=_llm_payload(drop_facts_citations=True))
    result = asyncio.run(ChatSynthesisService(provider).synthesize(
        question="q", ticker="AAA", baseline=_baseline()
    ))
    assert result.model == "deterministic"
    assert result.llm_trace["fallback_reason"] == "ValueError"



def test_missing_contract_section_falls_back():
    provider = StubProvider(payload=_llm_payload(skip_key="contradictions"))
    result = asyncio.run(ChatSynthesisService(provider).synthesize(
        question="q", ticker="AAA", baseline=_baseline()
    ))
    assert result.model == "deterministic"
    assert result.llm_trace["fallback"] is True



def test_no_financial_facts_caps_confidence_and_flags_insufficient():
    provider = StubProvider(payload=_llm_payload(citations=[]))
    result = asyncio.run(ChatSynthesisService(provider).synthesize(
        question="q", ticker=None, baseline=_baseline(with_facts=False)
    ))
    assert result.model == "stub-model"
    assert result.confidence <= 0.35
    assert result.insufficient_data is True



def test_provider_error_falls_back_with_reason():
    provider = StubProvider(error=TimeoutError("slow"))
    result = asyncio.run(ChatSynthesisService(provider).synthesize(
        question="q", ticker="AAA", baseline=_baseline()
    ))
    assert result.model == "deterministic"
    assert result.llm_trace["fallback_reason"] == "TimeoutError"
    assert result.llm_trace["cost"] is None



def test_budget_exhaustion_falls_back(monkeypatch, db_session=None):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.entities import Base
    from app.services.budget import BudgetController

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        monkeypatch.setattr(BudgetController, "can_spend", lambda self, db, amount: False)
        provider = StubProvider(payload=_llm_payload())
        result = asyncio.run(ChatSynthesisService(provider).synthesize(
            question="q", ticker="AAA", baseline=_baseline(), db=session
        ))
    assert result.model == "deterministic"
    assert result.llm_trace["fallback_reason"] == "BudgetExceededError"


def _two_source_baseline() -> ChatResponse:
    per_section = {"facts": ["financial_fact:1"], "calculations": ["market_price:2"]}
    sections = [
        SynthesisSection(key=key, body=f"baseline {key}", citations=per_section.get(key, []))
        for key in SECTION_ORDER
    ]
    sources = [{"type": "financial_fact", "id": 1}, {"type": "market_price", "id": 2}]
    return ChatResponse(answer="baseline answer", sections=sections, sources=sources)


def _per_section_payload(facts: list[str], calculations: list[str]) -> dict:
    payload = _llm_payload(citations=[])
    for section in payload["sections"]:
        if section["key"] == "facts":
            section["citations"] = facts
        if section["key"] == "calculations":
            section["citations"] = calculations
    return payload


def test_globally_valid_id_in_the_wrong_section_still_falls_back():
    """The validator is NOT relaxed: market_price:2 exists, but not in the facts baseline."""
    provider = StubProvider(payload=_per_section_payload(["financial_fact:1", "market_price:2"], ["market_price:2"]))
    result = asyncio.run(ChatSynthesisService(provider).synthesize(
        question="q", ticker="AAA", baseline=_two_source_baseline()
    ))
    assert result.model == "deterministic"
    assert result.llm_trace["fallback_reason"] == "ValueError"


def test_each_section_citing_its_own_ids_is_accepted():
    provider = StubProvider(payload=_per_section_payload(["financial_fact:1"], ["market_price:2"]))
    result = asyncio.run(ChatSynthesisService(provider).synthesize(
        question="q", ticker="AAA", baseline=_two_source_baseline()
    ))
    assert result.model == "stub-model"
    assert result.llm_trace["citation_verification"] is True


def test_prompt_states_the_per_section_citation_contract():
    from app.services.prompt_registry import get_prompt

    text = get_prompt("chat_source_synthesis", allow_remote=False).text
    assert "ONLY the IDs listed in that same section of deterministic_sections" in text
