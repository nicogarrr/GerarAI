"""Deterministic 13F answers preserve unknown fields and do not call a model."""
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.services import brain_13f_tools as brain
from app.services import investor_portfolio as portfolios


@pytest.mark.parametrize("en", [False, True])
def test_position_with_absent_datums_never_fabricates_shares_or_value(en):
    out = brain._position_line({"issuer": "Local Inc", "shares": None, "value_usd": "bad",
        "weight_pct": {"value": 0}, "note": "partial evidence"}, en)
    assert ("shares N/D" if en else "acciones N/D") in out
    assert ("value N/D" if en else "valor N/D") in out
    assert ("weight 0.00 %" if en else "peso 0,00 %") in out
    assert "partial evidence" in out


@pytest.mark.parametrize("en", [False, True])
def test_movement_missing_count_and_zero_count_are_distinct(en):
    missing = brain._movement_line({"issuer": "Local", "action": "aumento", "shares": None}, en)
    zero = brain._movement_line({"issuer": "Local", "action": "aumento", "shares": {"value": 0}, "shares_after": {"value": 10}}, en)
    assert "N/D" in missing
    assert ("increased, 0 shares (now 10)." if en else "aumentó, 0 acciones (ahora 10).") in zero
    assert "+0" not in zero and "-0" not in zero


@pytest.mark.parametrize("coverage", ["ok", "partial"])
def test_general_question_without_movements_uses_coverage_not_invented_changes(monkeypatch, coverage):
    load = Mock(return_value={"status": "ok", "as_of": "2026-06-30", "positions": [
        {"issuer": "Local Inc", "shares": {"value": 100}, "value_usd": {"value": 200}, "weight_pct": None}],
        "movements": [], "coverage": coverage})
    monkeypatch.setattr(portfolios, "investor_portfolio", load)
    monkeypatch.setattr(brain, "_english", lambda: True)
    db = Mock(spec=Session)
    answer = brain.answer_13f_question(db, "What is Buffett's latest 13F?")
    assert answer is not None
    assert "100 shares" in answer.answer and "$200" in answer.answer
    assert "Changes vs" not in answer.answer
    assert ("Source: the 13F-HR" if coverage == "ok" else "Partial coverage:") in answer.answer
    assert answer.sources[0]["id"] == "buffett"
    assert "filing_url" not in answer.sources[0]
    assert answer.llm_trace["provider_calls"] == 0
    load.assert_called_once_with(db, "buffett")


def test_named_issuer_without_computed_change_is_explicit_not_unchanged(monkeypatch):
    monkeypatch.setattr(portfolios, "investor_portfolio", lambda *_: {"status": "ok", "positions": [
        {"issuer": "APPLE INC", "shares": {"value": 100, "source_url": "https://example.com/13f"}}],
        "movements": [], "coverage": "partial"})
    monkeypatch.setattr(brain, "_english", lambda: True)
    db = Mock(spec=Session)
    answer = brain.answer_13f_question(db, "What is Buffett's Apple position in his 13F?")
    assert answer is not None
    assert "missing the change in APPLE INC" in answer.answer
    assert answer.sources[0]["filing_url"] == "https://example.com/13f"
