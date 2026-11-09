"""Consensus adapter fallback paths, isolated from remote analyst sources."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.models import Company
from app.services import thesis_consensus_service as control
from app.valuation.consensus_context import AnalystInputs, ConsensusSnapshot


@pytest.mark.parametrize("environment,flag", [("test", True), (" CI ", True), ("production", False)])
def test_default_settings_disable_without_loading_sources(monkeypatch, environment, flag):
    monkeypatch.setattr(
        control, "get_settings", lambda: SimpleNamespace(app_env=environment, consensus_control_enabled=flag)
    )

    def forbidden(*args):
        pytest.fail("disabled control must not read analyst sources")

    monkeypatch.setattr(control, "load_consensus", forbidden)
    valuation = {"base_value": 100, "publishable": True}
    before = deepcopy(valuation)
    assert control.apply_consensus_control(None, Company(ticker="TEST"), valuation) == {"status": "disabled"}
    assert valuation == before


def test_production_default_reports_missing_consensus_without_changing_value(monkeypatch):
    monkeypatch.setattr(
        control, "get_settings", lambda: SimpleNamespace(app_env="production", consensus_control_enabled=True)
    )
    monkeypatch.setattr(control, "load_consensus", lambda *args: None)
    valuation = {"base_value": 100, "publishable": True}
    result = control.apply_consensus_control(None, Company(ticker="TEST"), valuation)
    assert result["status"] == "sin_consenso" and result["threshold"] == 0.35
    assert valuation == {"base_value": 100, "publishable": True}


@pytest.mark.parametrize(
    "valuation,expected",
    [
        ({"currency": {"reporting_currency": "EUR"}}, "EUR"),
        ({"currency": {}, "trace": {}}, None),
        ({"currency": None, "trace": {"price_currency": " GBP "}}, "GBP"),
        ({"value_currency": "USD", "price_currency": "EUR", "currency": "GBP"}, "USD"),
    ],
)
def test_currency_precedence_and_absent_units(valuation, expected):
    assert control._our_currency(valuation) == expected
    assert control._major(None) is None


@pytest.mark.parametrize("bad", [True, None, "invalid", object(), 10**400, -1, 0])
def test_our_value_falls_back_to_positive_expected_value(bad):
    assert control._our_value({"base_value": bad, "expected_value": "75"}) == 75
    assert control._our_value({"base_value": bad}) is None


def test_missing_currency_and_target_values_are_reported_not_invented(monkeypatch):
    snapshot = ConsensusSnapshot(symbol="TEST", status="empty")
    monkeypatch.setattr(control, "load_consensus", lambda *args: snapshot)
    monkeypatch.setattr(control, "analyst_inputs_for_dcf", lambda *args: AnalystInputs())
    valuation = {"expected_value": 100, "publishable": True, "trace": {}}
    result = control.apply_consensus_control(None, Company(ticker="TEST"), valuation, enabled=True)
    assert result["comparison"] == {
        "unit": None,
        "consensus_unit": None,
        "factor": 1.0,
        "consensus_mean": None,
        "consensus_low": None,
        "consensus_high": None,
    }
    assert result["our_value_basis"] == "expected_value"
    assert result["data_rows"][0]["value"] == 100
    assert result["consensus_basis"] == "median"


def test_blocker_fallback_deduplicates_when_sanity_writer_does_not_mutate(monkeypatch):
    snapshot = ConsensusSnapshot(symbol="TEST", status="available", mean=50, currency="USD")
    monkeypatch.setattr(control, "load_consensus", lambda *args: snapshot)
    monkeypatch.setattr(control, "analyst_inputs_for_dcf", lambda *args: AnalystInputs())
    monkeypatch.setattr(control, "apply_consensus_sanity", lambda *args, **kwargs: None)
    valuation = {
        "base_value": 100,
        "currency": "USD",
        "publishable": True,
        "publication_blockers": ["existing"],
        "trace": {},
    }
    for _ in range(2):
        result = control.apply_consensus_control(None, Company(ticker="TEST"), valuation, enabled=True)
        assert result["status"] == "revisar"
    assert valuation["publishable"] is False
    assert valuation["publication_blockers"] == ["existing", control.REVIEW_BLOCKER]
