"""Jev triage boundaries with local client decisions only, no paid requests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.llm import jev
from app.services import jev_availability as availability
from app.services import jev_triage_service as triage


@pytest.mark.parametrize("guard_required", [False, True])
def test_build_client_propagates_configuration(monkeypatch, guard_required):
    settings = SimpleNamespace(
        typesafe_api_key="synthetic-key",
        typesafe_base_url="https://fixture.test",
        typesafe_model="fixture-model",
        llm_run_guard_required=guard_required,
    )
    factory = Mock(return_value=SimpleNamespace())
    monkeypatch.setattr(triage, "get_settings", lambda: settings)
    monkeypatch.setattr(jev, "JevDecisionClient", factory)
    client = triage.build_client()
    factory.assert_called_once_with(
        api_key="synthetic-key", base_url="https://fixture.test", default_model="fixture-model"
    )
    assert client.guard_required is guard_required


@pytest.mark.parametrize("function", [triage.classify_urgency_sync, triage.classify_doc_type_sync])
@pytest.mark.parametrize("status", ["desactivado_sin_credito", "estado_no_disponible", "sin_configurar"])
def test_inactive_credit_never_builds_client(monkeypatch, function, status):
    factory = Mock(side_effect=AssertionError("must not build client"))
    monkeypatch.setattr(availability, "credit_status", lambda: {"status": status})
    monkeypatch.setattr(triage, "build_client", factory)
    assert function("fixture text") is None
    factory.assert_not_called()


@pytest.mark.parametrize("function", [triage.classify_urgency_sync, triage.classify_doc_type_sync])
def test_active_without_client_is_noop(monkeypatch, function):
    monkeypatch.setattr(availability, "credit_status", lambda: {"status": "activo"})
    monkeypatch.setattr(triage, "build_client", lambda: None)
    assert function("fixture") is None


@pytest.mark.parametrize(
    "function,name,criteria",
    [
        (triage.classify_urgency_sync, "urgency", triage.CRITERIA),
        (triage.classify_doc_type_sync, "doc_type", triage.DOC_TYPE_CRITERIA),
    ],
)
def test_success_truncates_text_and_preserves_decision(monkeypatch, function, name, criteria):
    monkeypatch.setattr(availability, "credit_status", lambda: {"status": "activo"})
    decision = SimpleNamespace(
        label="fixture-label", confidence=0.917, latency_s=0.25, backend="local-fixture"
    )
    classify = AsyncMock(return_value=decision)
    monkeypatch.setattr(triage, "build_client", lambda: SimpleNamespace(classify=classify))
    result = function("x" * 2001)
    assert result == triage.JevTriageResult("fixture-label", 0.917, False, 0.25, backend="local-fixture")
    args, kwargs = classify.call_args
    assert args == ("x" * 2000,)
    assert kwargs["name"] == name and kwargs["criteria"] is criteria
    assert isinstance(kwargs["instructions"], str) and kwargs["instructions"]
    classify.assert_awaited_once()


@pytest.mark.parametrize("function", [triage.classify_urgency_sync, triage.classify_doc_type_sync])
@pytest.mark.parametrize("credit_error", [False, True])
def test_failure_is_soft_and_only_credit_exhaustion_marks_credit(monkeypatch, function, credit_error):
    monkeypatch.setattr(availability, "credit_status", lambda: {"status": "activo"})
    mark = Mock()
    monkeypatch.setattr(availability, "mark_credit_exhausted", mark)
    error = jev.JevCreditExhausted("local exhausted") if credit_error else RuntimeError("local failure")
    classify = AsyncMock(side_effect=error)
    monkeypatch.setattr(triage, "build_client", lambda: SimpleNamespace(classify=classify))
    result = function("fixture")
    assert result.label == "" and result.confidence == 0 and result.latency_s == 0
    assert result.applied is False
    assert result.error == f"{type(error).__name__}: {error}"
    classify.assert_awaited_once()
    assert mark.call_count == int(credit_error)


def test_metadata_preserves_backend_rounds_confidence_and_caps_error():
    result = triage.JevTriageResult("urgent", 0.123456, False, 0.7, "x" * 201, "fixture")
    assert triage.jev_metadata(result) == {
        "label": "urgent",
        "confidence": 0.1235,
        "latency_s": 0.7,
        "backend": "fixture",
        "error": "x" * 200,
    }
    assert result.error == "x" * 201


@pytest.mark.parametrize(
    "label,confidence,expected,reason",
    [
        ("urgent", 0.80, 6, "jev_urgent(conf=0.80) +1"),
        ("routine", 0.85, 4, "jev_routine(conf=0.85) -1"),
        ("urgent", 0.799, 5, None),
        ("routine", 0.849, 5, None),
    ],
)
def test_materiality_confidence_thresholds_are_inclusive(label, confidence, expected, reason):
    reasons = ["existing"]
    assert (
        triage.apply_to_materiality(5, reasons, triage.JevTriageResult(label, confidence, False, 0))
        == expected
    )
    assert reasons == (["existing", reason] if reason else ["existing"])


def test_build_client_without_key_never_constructs_client(monkeypatch):
    factory = Mock(side_effect=AssertionError("must not construct client"))
    monkeypatch.setattr(triage, "get_settings", lambda: SimpleNamespace(typesafe_api_key=None))
    monkeypatch.setattr(jev, "JevDecisionClient", factory)
    assert triage.build_client() is None
    factory.assert_not_called()
