"""Fail-closed extractive research wording with no paid provider calls."""

import asyncio
import copy
import json
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.llm import LLMResponse, Message, Usage
from app.services import llm_output_guard as guard
from app.services import research_assistant_narrative as narrative

CITATIONS = [
    {"id": "fact:1", "kind": "financial_fact", "excerpt": "Caja neta 10"},
    {"id": "fact:2", "kind": "financial_fact", "excerpt": "Caja neta 10"},
]


@pytest.fixture(autouse=True)
def isolated_guard_stats(monkeypatch):
    monkeypatch.setattr(guard, "_stats", Counter(guard.guard_stats()))


@pytest.mark.parametrize("payload", [None, [], {"sentences": None}, {"sentences": "bad"}])
def test_invalid_sentence_container_is_empty(payload):
    assert narrative._validated_sentences(payload, CITATIONS) == []


@pytest.mark.parametrize(
    "item",
    [
        None,
        "bad",
        {"body": 10, "citation_ids": ["fact:1"]},
        {"body": "", "citation_ids": ["fact:1"]},
        {"body": "Caja neta 10", "citation_ids": None},
        {"body": "Caja neta 10", "citation_ids": []},
        {"body": "Caja neta 10", "citation_ids": ["unknown"]},
        {"body": "Caja neta 10", "citation_ids": ["fact:1", "fact:2"]},
        {"body": "Caja neta 10", "citation_ids": ["fact:1", "fact:1"]},
        {"body": "Caja neta 11", "citation_ids": ["fact:1"]},
    ],
)
def test_invalid_sentence_never_becomes_a_claim(item):
    assert narrative._validated_sentences({"sentences": [item]}, CITATIONS) == []


@pytest.mark.parametrize("length,accepted", [(400, True), (401, False)])
def test_body_length_boundary_and_single_exact_excerpt(length, accepted):
    body = "x" * length
    citations = [{"id": "one", "excerpt": body}]
    item = {"body": body, "citation_ids": ["one"]}
    result = narrative._validated_sentences({"sentences": [item]}, citations)
    assert result == ([item] if accepted else [])


def test_six_sentence_cap_and_whitespace_normalization():
    item = {"body": "  Caja neta 10  ", "citation_ids": ["fact:1"]}
    result = narrative._validated_sentences({"sentences": [item] * 7}, CITATIONS)
    assert result == [{"body": "Caja neta 10", "citation_ids": ["fact:1"]}] * 6
    assert item["body"] == "  Caja neta 10  "


def baseline():
    return {
        "status": "answered",
        "citations": copy.deepcopy(CITATIONS),
        "answer": "Safe deterministic answer",
        "sections": [],
    }


def test_calculation_only_baseline_never_selects_provider_or_budget(monkeypatch):
    choose = Mock(side_effect=AssertionError("provider must not be selected"))
    budget = Mock(side_effect=AssertionError("budget must not be touched"))
    monkeypatch.setattr(narrative, "create_chat_llm_provider", choose)
    monkeypatch.setattr(narrative, "BudgetController", budget)
    original = baseline()
    original["citations"] = [{"id": "calc:1", "kind": "calculation", "excerpt": "Local calculation"}]
    before = copy.deepcopy(original)
    assert asyncio.run(narrative.synthesize(None, None, original)) is original
    assert original == before
    choose.assert_not_called()
    budget.assert_not_called()


def test_disabled_provider_preserves_answer_without_budget(monkeypatch):
    choose = Mock(return_value=SimpleNamespace(name="disabled"))
    budget = Mock(side_effect=AssertionError("budget must not be touched"))
    monkeypatch.setattr(narrative, "create_chat_llm_provider", choose)
    monkeypatch.setattr(narrative, "BudgetController", budget)
    original = baseline()
    before = copy.deepcopy(original)
    assert asyncio.run(narrative.synthesize(None, None, original)) is original
    assert original == before
    choose.assert_called_once_with()
    budget.assert_not_called()


def test_initial_budget_denial_never_calls_provider(monkeypatch):
    budget = Mock()
    budget.can_spend.return_value = False
    monkeypatch.setattr(narrative, "BudgetController", lambda: budget)
    provider = SimpleNamespace(name="stub", complete=AsyncMock())
    original = baseline()
    before = copy.deepcopy(original)
    assert asyncio.run(narrative.synthesize(None, None, original, provider=provider)) is original
    assert original == before
    budget.can_spend.assert_called_once_with(None, 0.02)
    provider.complete.assert_not_awaited()
    budget.record.assert_not_called()


@pytest.mark.parametrize(
    "reply,allowed",
    [
        ("{not JSON", [True]),
        (json.dumps({"sentences": []}), [True]),
        (json.dumps({"sentences": [{"body": "Caja 文化", "citation_ids": ["fact:1"]}]}), [True, False]),
    ],
)
def test_invalid_output_or_exhausted_retry_preserves_baseline_and_records_cost(monkeypatch, reply, allowed):
    budget = Mock()
    budget.can_spend.side_effect = allowed
    budget.estimate_cost_eur.return_value = 0.001
    monkeypatch.setattr(narrative, "BudgetController", lambda: budget)
    response = LLMResponse(Message("assistant", reply), Usage(10, 5, 15), "stub-model", "stub")
    provider = SimpleNamespace(name="stub", complete=AsyncMock(return_value=response))
    original = baseline()
    before = copy.deepcopy(original)
    payload = SimpleNamespace(question="Question", mode="research")
    assert asyncio.run(narrative.synthesize(None, payload, original, provider=provider)) is original
    assert original == before
    provider.complete.assert_awaited_once()
    budget.estimate_cost_eur.assert_called_once_with("stub-model", 10, 5)
    budget.record.assert_called_once_with(None, "stub-model", "research_assistant_narrative", 0.001, 15)
    assert budget.can_spend.call_count == len(allowed)


@pytest.mark.parametrize("status,citations", [("unavailable", CITATIONS), ("answered", [])])
def test_unanswered_or_uncited_baseline_never_selects_provider(monkeypatch, status, citations):
    choose = Mock(side_effect=AssertionError("provider must not be selected"))
    monkeypatch.setattr(narrative, "create_chat_llm_provider", choose)
    original = baseline()
    original.update(status=status, citations=citations)
    before = copy.deepcopy(original)
    assert asyncio.run(narrative.synthesize(None, None, original)) is original
    assert original == before
    choose.assert_not_called()
