"""Telemetría propia de /api/chat (€0): clasificación y persistencia."""
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models import ChatTelemetryEvent, Tenant
from app.services import chat_telemetry


def _response(path=None, provider=None, model=None, fallback=False):
    trace = {}
    if path:
        trace["path"] = path
    if provider:
        trace["provider"] = provider
    if model:
        trace["model"] = model
    if fallback:
        trace["fallback"] = True
    return SimpleNamespace(llm_trace=trace, model=model or "small-talk")


def test_classify_llm_synthesis():
    route, used_llm = chat_telemetry.classify_response(
        _response(provider="opencode-go", model="deepseek-v4.1-flash-free")
    )
    assert route == "chat_synthesis"
    assert used_llm is True


def test_classify_deterministic_paths():
    assert chat_telemetry.classify_response(_response(path="small_talk")) == ("small_talk", False)
    assert chat_telemetry.classify_response(_response(path="portfolio_overview")) == ("portfolio_overview", False)


def test_classify_fallback_is_not_llm():
    route, used_llm = chat_telemetry.classify_response(
        _response(provider="opencode-go", model="deterministic", fallback=True)
    )
    assert used_llm is False


def test_record_chat_event_persists_with_tenant_context(monkeypatch):
    from app.core import database as database_module

    monkeypatch.setattr(database_module.settings, "research_auth_required", True)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(external_id="t1", name="Uno", status="active"))
        db.commit()
    monkeypatch.setattr(chat_telemetry, "SessionLocal", sessionmaker(engine))
    chat_telemetry.record_chat_event(
        tenant_id=1, question="¿a cuánto está ASTS?", route="chat_synthesis",
        used_llm=True, model="deepseek-v4.1-flash-free", latency_ms=94600,
    )
    chat_telemetry.record_chat_event(
        tenant_id=1, question="hola", route="error", used_llm=False,
        model=None, latency_ms=12, error="RuntimeError: boom",
    )
    with Session(engine) as db:
        rows = db.scalars(select(ChatTelemetryEvent).order_by(ChatTelemetryEvent.id)).all()
        assert len(rows) == 2
        assert rows[0].question == "¿a cuánto está ASTS?"
        assert rows[0].used_llm is True and rows[0].latency_ms == 94600
        assert rows[1].route == "error" and rows[1].error == "RuntimeError: boom"
        assert {row.tenant_id for row in rows} == {1}


def test_record_chat_event_never_raises(monkeypatch):
    monkeypatch.setattr(
        chat_telemetry, "SessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("db down"))
    )
    chat_telemetry.record_chat_event(
        tenant_id=1, question="q", route="error", used_llm=False,
        model=None, latency_ms=1, error="x",
    )
