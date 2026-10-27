import pytest
from pydantic import ValidationError

from app.api.routes.research_assistant import AssistantRequest
from app.services.research_assistant_narrative import _prompt_payload


def _turns(n):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turno {i}"} for i in range(n)]


def test_request_accepts_bounded_history():
    req = AssistantRequest(mode="guide", question="¿y la deuda?", ticker="AAPL", history=_turns(8))
    assert len(req.history) == 8
    with pytest.raises(ValidationError):
        AssistantRequest(mode="guide", question="¿y la deuda?", ticker="AAPL", history=_turns(9))


def test_request_history_defaults_to_empty():
    assert AssistantRequest(mode="explore", question="hola").history == []


def test_prompt_carries_history_as_context_without_private_portfolio_turns():
    req = AssistantRequest(mode="guide", question="¿y la deuda?", ticker="AAPL", history=[
        {"role": "user", "content": "háblame de AAPL"},
        {"role": "assistant", "content": "Tus posiciones abiertas: 10 AAPL a 150"},
        {"role": "assistant", "content": "Apple vende iPhone."},
    ])
    data = _prompt_payload(req, [{"id": "financial_fact:1"}])
    assert data["question"] == "¿y la deuda?"
    contents = [t["content"] for t in data["history"]]
    assert contents == ["háblame de AAPL", "Apple vende iPhone."]


def test_prompt_without_history_has_empty_list():
    req = AssistantRequest(mode="explore", question="hola mundo")
    assert _prompt_payload(req, [])["history"] == []
