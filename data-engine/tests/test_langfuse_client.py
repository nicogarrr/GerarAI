from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from app.services.langfuse_client import LangfuseTracer


class _FakeSpan:
    def __init__(self) -> None:
        self.updates: list[dict] = []
        self.ended = False

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)

    def end(self) -> None:
        self.ended = True


class _FakeLangfuse:
    instances: list[_FakeLangfuse] = []

    def __init__(self, **_kwargs) -> None:
        self.span = _FakeSpan()
        self.started: list[dict] = []
        self.flushed = False
        _FakeLangfuse.instances.append(self)

    def start_observation(self, **kwargs):
        self.started.append(kwargs)
        return self.span

    def flush(self) -> None:
        self.flushed = True


def _tracer(monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> LangfuseTracer:
    _FakeLangfuse.instances.clear()
    monkeypatch.setitem(sys.modules, "langfuse", types.SimpleNamespace(Langfuse=_FakeLangfuse))
    tracer = LangfuseTracer()
    tracer.settings = SimpleNamespace(  # type: ignore[assignment]
        langfuse_enabled=enabled,
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        langfuse_host="http://localhost:1",
    )
    return tracer


def test_workflow_uses_start_observation_and_ends_span(monkeypatch: pytest.MonkeyPatch) -> None:
    tracer = _tracer(monkeypatch, enabled=True)
    with tracer.workflow("Wf", {"model": "m1", "question": "PRIVATE TEXT"}) as trace:
        trace.output = {"ok": True}
    client = _FakeLangfuse.instances[0]
    assert len(client.started) == 1
    assert client.started[0]["name"] == "Wf"
    assert client.started[0]["metadata"] == {"model": "m1"}  # allowlist: sin texto de usuario
    assert client.span.updates[0]["output"] == {"ok": True}
    assert client.span.updates[0]["level"] == "DEFAULT"
    assert client.span.ended and client.flushed
    assert "telemetry_setup_error" not in trace.metadata
    assert "telemetry_flush_error" not in trace.metadata


def test_workflow_marks_error_level(monkeypatch: pytest.MonkeyPatch) -> None:
    tracer = _tracer(monkeypatch, enabled=True)
    with pytest.raises(ValueError):
        with tracer.workflow("Wf"):
            raise ValueError("boom")
    update = _FakeLangfuse.instances[0].span.updates[0]
    assert update["level"] == "ERROR"
    assert update["status_message"] == "ValueError"


def test_workflow_disabled_never_touches_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    tracer = _tracer(monkeypatch, enabled=False)
    with tracer.workflow("Wf") as trace:
        pass
    assert _FakeLangfuse.instances == []
    assert "latency_ms" in trace.metadata


def test_remote_trace_never_receives_free_text(monkeypatch: pytest.MonkeyPatch) -> None:
    tracer = _tracer(monkeypatch, enabled=True)
    with tracer.workflow("Wf", {"model": "m1"}) as trace:
        trace.update(answer="TEXT FROM USER DOC", cost=0.01)
        trace.output = {"confidence": 0.7, "answer": "SECRET BODY"}
    update = _FakeLangfuse.instances[0].span.updates[0]
    assert "answer" not in update["metadata"]
    assert update["metadata"]["cost"] == 0.01
    assert "latency_ms" in update["metadata"]
    assert update["output"] == {"confidence": 0.7}
