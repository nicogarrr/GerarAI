"""Stage 3: Langfuse shadow tracing — muestreo, fallos siempre, redaccion."""


import pytest

from app.core.config import get_settings
from app.core.database import SessionLocal, init_db
from app.models.entities import WorkflowRun
from app.services import tracing
from app.services.workflow_run_service import begin_run


class FakeSpan:
    def __init__(self, sink, kind, kwargs):
        self.sink = sink
        self.kind = kind
        self.kwargs = kwargs

    def start_observation(self, *, as_type="span", **kwargs):
        # SDK 4.x: start_span/start_generation ya no existen.
        span = FakeSpan(self.sink, as_type, kwargs)
        self.sink.append(span)
        return span

    def update(self, **kwargs):
        self.kwargs.setdefault("updates", []).append(kwargs)

    def end(self):
        self.kwargs["ended"] = True


class FakeClient:
    def __init__(self, sink):
        self.sink = sink

    def create_trace_id(self):
        return "trace-1"

    def start_observation(self, **kwargs):
        span = FakeSpan(self.sink, "root", kwargs)
        self.sink.append(span)
        return span

    def flush(self):
        self.sink.append("flushed")


@pytest.fixture
def sink():
    return []


@pytest.fixture
def factory(sink):
    return lambda: FakeClient(sink)


@pytest.fixture(autouse=True)
def langfuse_on(monkeypatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _db():
    init_db()
    return SessionLocal()


def _cleanup(db):
    from app.models.entities import WorkflowStepRun

    db.query(WorkflowStepRun).delete()
    db.query(WorkflowRun).delete()
    db.commit()


def test_disabled_means_no_client_and_no_crash(monkeypatch, sink):
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    get_settings.cache_clear()
    tracer = tracing.begin_trace(
        "X", run_id=1, metadata={}, client_factory=lambda: FakeClient(sink)
    )
    with tracer.step(1, "s"):
        pass
    tracer.finish(status="succeeded")
    assert sink == []


def test_sampled_out_success_sends_nothing(factory, sink):
    tracer = tracing.begin_trace(
        "X", run_id=1, metadata={}, client_factory=factory, sample_decision=False
    )
    with tracer.step(1, "s"):
        pass
    tracer.finish(status="succeeded")
    assert sink == []


def test_failure_is_traced_even_when_sampled_out(factory, sink):
    tracer = tracing.begin_trace(
        "X", run_id=1, metadata={}, client_factory=factory, sample_decision=False
    )
    with pytest.raises(ValueError):
        with tracer.step(1, "explota"):
            raise ValueError("boom")
    tracer.finish(status="failed", error_class="ValueError")
    kinds = [getattr(item, "kind", None) for item in sink]
    assert "root" in kinds
    assert "flushed" in sink
    root = next(i for i in sink if getattr(i, "kind", None) == "root")
    assert root.kwargs["metadata"]["workflow_name"] == "X"
    child = next(i for i in sink if getattr(i, "kind", None) == "span")
    assert child.kwargs["name"] == "explota"
    assert child.kwargs["level"] == "ERROR"


def test_metadata_allowlist_redacts(factory, sink):
    tracer = tracing.begin_trace(
        "X",
        run_id=1,
        metadata={
            "workflow_name": "X",
            "api_key": "SECRET",
            "prompt_text": "no sale",
            "tenant_hash": "abc",
        },
        client_factory=factory,
        sample_decision=True,
    )
    with tracer.step(1, "s"):
        pass
    tracer.finish(status="succeeded")
    root = next(i for i in sink if getattr(i, "kind", None) == "root")
    assert root.kwargs["metadata"] == {"workflow_name": "X", "tenant_hash": "abc", "run_id": 1}
    # Ningun span lleva input/output.
    for item in sink:
        if hasattr(item, "kwargs"):
            assert "input" not in item.kwargs
            assert "output" not in item.kwargs


def test_generation_span_carries_usage_not_prompts(factory, sink):
    tracer = tracing.begin_trace(
        "X", run_id=1, metadata={}, client_factory=factory, sample_decision=True
    )
    token = tracing.set_current_tracer(tracer)
    try:
        tracing.trace_generation(
            name="llm.chat",
            model="deepseek-v4-flash",
            metadata={"provider": "opencode-go", "task": "chat", "system_prompt": "NO"},
            usage={"input": 10, "output": 5, "total": 15},
        )
    finally:
        tracing.reset_current_tracer(token)
    tracer.finish(status="succeeded")
    gen = next(i for i in sink if getattr(i, "kind", None) == "generation")
    assert gen.kwargs["model"] == "deepseek-v4-flash"
    assert gen.kwargs["usage_details"] == {"input": 10, "output": 5, "total": 15}
    assert gen.kwargs["metadata"] == {"provider": "opencode-go", "task": "chat"}
    assert "prompt" not in gen.kwargs


def test_envelope_traces_full_run(factory, sink, monkeypatch):
    monkeypatch.setenv("LANGFUSE_SAMPLE_RATE", "1.0")
    get_settings.cache_clear()
    original_begin_trace = tracing.begin_trace

    def fake_begin(workflow_name, *, run_id=None, metadata=None):
        return original_begin_trace(
            workflow_name, run_id=run_id, metadata=metadata,
            client_factory=factory, sample_decision=True,
        )

    monkeypatch.setattr(
        "app.services.workflow_run_service.tracing.begin_trace", fake_begin
    )
    db = _db()
    try:
        _cleanup(db)
        envelope = begin_run(db, "GenerateThesisWorkflow", idempotency_key="trace-1")
        envelope.record_step(1, "generate_thesis", lambda: {"thesis_id": 1})
        envelope.finish({"status": "completed"})
        kinds = [getattr(i, "kind", None) for i in sink]
        assert kinds.count("root") == 1
        assert "span" in kinds
        assert "flushed" in sink
        root = next(i for i in sink if getattr(i, "kind", None) == "root")
        assert root.kwargs["metadata"]["run_id"] == envelope.run.id
        updates = root.kwargs.get("updates", [])
        assert updates and updates[-1]["metadata"]["status"] == "succeeded"
    finally:
        _cleanup(db)
        db.close()


def test_tracer_funciona_contra_el_sdk_real_de_langfuse():
    """Contrato con langfuse 4.x real (sin red: tracing_enabled=False).

    Los fakes de arriba no detectarian que el SDK renombre la API; el tracer
    envuelve todo en try/except, asi que un renombrado perderia las trazas en silencio.
    """
    langfuse = pytest.importorskip("langfuse")
    client = langfuse.Langfuse(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="http://127.0.0.1:9",
        tracing_enabled=False,
    )
    tracer = tracing.ShadowTracer(
        client_factory=lambda: client,
        workflow_name="wf",
        run_id=1,
        metadata={},
        active=True,
    )
    tracer._start_root()
    assert type(tracer._root).__name__ == "LangfuseSpan"
    child = tracer._root.start_observation(as_type="span", name="paso", metadata={"x": "y"})
    child.end()
    generation = tracer._root.start_observation(
        as_type="generation", name="gen", model="m", usage_details={"input": 1, "output": 2}
    )
    assert type(generation).__name__ == "LangfuseGeneration"
    generation.end()
    tracer._root.end()
    client.flush()
