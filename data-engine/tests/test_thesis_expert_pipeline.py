"""El roster se consume antes del modelo y consenso solo diagnostica."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.config import get_settings
from app.services import thesis_service as thesis
from app.services.expert_team import analyst_blend, esceptico, recopilador, roster, service


def test_off_and_stored_do_not_enter_pipeline(monkeypatch):
    run = AsyncMock()
    monkeypatch.setattr(thesis, "_run_thesis_experts", run)
    monkeypatch.setattr(get_settings(), "expert_team_enabled", False)
    assert thesis._prepare_thesis_experts(None, "TSLA", stored_evidence_only=False) is None
    monkeypatch.setattr(get_settings(), "expert_team_enabled", True)
    assert thesis._prepare_thesis_experts(None, "CHTR", stored_evidence_only=True) is None
    run.assert_not_called()


def test_team_timeout_or_failure_never_breaks_the_thesis(monkeypatch):
    monkeypatch.setattr(get_settings(), "expert_team_enabled", True)

    async def boom(db, ticker):
        raise TimeoutError

    monkeypatch.setattr(thesis, "_run_thesis_experts", boom)
    out = thesis._prepare_thesis_experts(None, "TSLA", stored_evidence_only=False)
    assert out == {"stages": [], "error": "TimeoutError", "consensus": None}
    assert thesis._expert_inputs_from_pipeline(out) == {"status": "error:TimeoutError"}
    assert thesis._experts_timeout() > 120


def test_roster_specs_are_consumed_in_order_and_same_session(monkeypatch):
    specs = roster.pipeline_experts()
    # Modified specs prove callers do not quietly replace them with defaults.
    specs[0] = replace(specs[0], max_tokens=123)
    roster_call = Mock(return_value=specs)
    monkeypatch.setattr(roster, "pipeline_experts", roster_call)
    db, ctx, reason = object(), object(), object()
    monkeypatch.setattr(service, "run_context", Mock(return_value=ctx))
    provider = Mock(return_value=reason)
    monkeypatch.setattr(service, "provider_reasoner", provider)
    calls = []

    async def first(session, **kw):
        assert session is db and kw["ctx"] is ctx and kw["reasoner"] is reason
        assert kw["spec"] is specs[0] and kw["spec"].max_tokens == 123
        calls.append("first")
        return SimpleNamespace(as_dict=lambda: {"status": "stored", "stored": 1})

    async def second(session, **kw):
        assert calls == ["first"] and session is db and kw["spec"] is specs[1]
        calls.append("second")
        await kw["load_history"]("TSLA")
        return SimpleNamespace(as_dict=lambda: {"status": "full_data"})

    async def third(session, **kw):
        assert calls == ["first", "second"] and session is db and kw["spec"] is specs[2]
        calls.append("third")
        return SimpleNamespace(beliefs=[], as_dict=lambda: {"status": "ok", "beliefs": []})

    monkeypatch.setattr(recopilador, "run_recopilador", first)
    monkeypatch.setattr(analyst_blend, "run_analyst_blend", second)
    monkeypatch.setattr(esceptico, "run_esceptico", third)
    from app.services.analyst_history_service import analyst_history_service
    history = AsyncMock(return_value=SimpleNamespace(consensus=SimpleNamespace(mean=200), source_url="source"))
    monkeypatch.setattr(analyst_history_service, "get", history)
    monkeypatch.setattr(get_settings(), "expert_team_enabled", True)
    out = thesis._prepare_thesis_experts(db, "TSLA", stored_evidence_only=False)
    assert calls == ["first", "second", "third"]
    assert [s["name"] for s in out["stages"]] == [s.name for s in specs]
    assert out["stages"][0]["stored"] == 1
    assert out["consensus"] == 200
    history.assert_awaited_once_with("TSLA")
    provider.assert_called_once_with(db=db, commit_usage=False)
    roster_call.assert_called_once()


@pytest.mark.parametrize("ticker", ["TSLA", "CHTR", "OTHER"])
def test_consensus_hook_does_not_cap_or_veto(ticker):
    valuation = {"status": "ok", "publishable": True, "publication_blockers": [],
                 "base_value": 100, "value_per_share": 100, "scenarios": {"bull": 400}, "trace": {"engine": "other"}}
    thesis._apply_thesis_consensus(valuation, {"consensus": 10, "stages": [], "ticker": ticker})
    assert valuation["trace"]["consensus_reconciliation"]["status"] == "revisar"
    assert valuation["value_per_share"] == 100 and valuation["scenarios"]["bull"] == 400
    assert valuation["status"] == "ok" and valuation["publishable"] is True
    assert valuation["publication_blockers"] == []


def test_running_loop_never_leaves_session_writes_in_background(monkeypatch):
    monkeypatch.setattr(get_settings(), "expert_team_enabled", True)
    run = AsyncMock()
    monkeypatch.setattr(thesis, "_run_thesis_experts", run)

    async def in_loop():
        with pytest.raises(RuntimeError, match="fuera del event loop"):
            thesis._prepare_thesis_experts(None, "TSLA", stored_evidence_only=False)
    asyncio.run(in_loop())
    run.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_atomic_generation_runs_pipeline_before_model_and_valuation(monkeypatch, enabled):
    from app.services.thesis_evidence_service import ThesisEvidenceService
    events = []
    company = SimpleNamespace(id=1, ticker="TSLA")
    monkeypatch.setattr(thesis, "resolve_company", lambda *a: company)
    monkeypatch.setattr(ThesisEvidenceService, "collect", lambda *a: {})
    monkeypatch.setattr(get_settings(), "expert_team_enabled", enabled)

    async def pipeline(db, ticker):
        events.append("experts")
        return {"stages": [{"name": "recopilador", "stored": 3}], "consensus": 10}

    monkeypatch.setattr(thesis, "_run_thesis_experts", pipeline)

    def model(*a, **kw):
        events.append("model")
        return {}

    monkeypatch.setattr(thesis.LongTermModelService, "build", model)
    valuation = {"status": "ok", "base_value": 100, "publishable": True, "trace": {}}
    svc = thesis.ThesisService()

    def value(*a):
        events.append("valuation")
        return valuation

    monkeypatch.setattr(svc.valuation_service, "value_company", value)

    class StopAfterValuation(Exception):
        pass

    def stop(*a, **kw):
        raise StopAfterValuation

    monkeypatch.setattr(svc, "_input_fingerprint", stop)
    with pytest.raises(StopAfterValuation):
        svc._generate_atomic(object(), "TSLA")
    assert events == (["experts"] if enabled else []) + ["model", "valuation"]
    assert ("expert_pipeline" in valuation["trace"]) is enabled
    assert valuation["publishable"] is True and valuation["base_value"] == 100
    if enabled:
        assert valuation["trace"]["expert_pipeline"]["stages"][0]["stored"] == 3


def test_reasoner_budget_usage_stays_in_thesis_transaction(monkeypatch):
    from app.services import budget, llm_output_guard
    db = SimpleNamespace(flush=Mock())
    record = Mock()
    monkeypatch.setattr(budget.BudgetController, "can_spend", lambda *a: True)
    monkeypatch.setattr(budget.BudgetController, "record", record)
    monkeypatch.setattr(budget.BudgetController, "estimate_cost_eur", lambda *a: 0.01)
    response = SimpleNamespace(text="texto", model="fixture", usage=SimpleNamespace(
        input_tokens=1, output_tokens=2, total_tokens=3,
    ))

    async def complete(provider, request, **kw):
        kw["on_response"](response)
        return SimpleNamespace(response=response)

    monkeypatch.setattr(llm_output_guard, "complete_guarded", complete)
    reason = service.provider_reasoner(object(), db=db, commit_usage=False)
    assert asyncio.run(reason("system", "user", 100, "thesis.experts")) == "texto"
    record.assert_called_once_with(db, "fixture", "thesis.experts", 0.01, 3, commit=False)
    db.flush.assert_called_once()


def test_history_failure_is_diagnostic_not_invented_consensus(monkeypatch):
    monkeypatch.setattr(roster, "pipeline_experts", lambda: [])
    monkeypatch.setattr(service, "run_context", lambda *a, **kw: object())
    monkeypatch.setattr(service, "provider_reasoner", lambda **kw: object())
    from app.services.analyst_history_service import analyst_history_service
    monkeypatch.setattr(analyst_history_service, "get", AsyncMock(side_effect=TimeoutError))
    out = asyncio.run(thesis._run_thesis_experts(None, "CHTR"))
    assert out == {"stages": [], "consensus": None, "consensus_error": "TimeoutError"}
