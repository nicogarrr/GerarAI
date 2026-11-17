"""Real SQLite transaction and actor regression tests for invalid extraction."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.services.knowledge_library_service as kls
import app.workers.dramatiq_app as workers
from app.core.database import Base
from app.llm import LLMResponse, Message, Usage
from app.llm.errors import ProviderDisabledError, StructuredOutputError
from app.models import BudgetUsage, KnowledgeChunk, KnowledgeDocument, ProcessingJob, Tenant


@pytest.mark.parametrize("hy4_mode", [False, True])
@pytest.mark.parametrize("invalid_text", ["not JSON", '{"principles": "invalid"}'])
def test_invalid_response_commits_usage_and_actor_diagnostic(tmp_path, monkeypatch, hy4_mode, invalid_text):
    engine = create_engine(f"sqlite:///{tmp_path / 'diagnostic.db'}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        tenant = Tenant(external_id="diagnostic", name="Diagnostic")
        db.add(tenant)
        db.flush()
        tid = tenant.id
        db.info["tenant_id"] = tid
        doc = KnowledgeDocument(tenant_id=tid, title="Private document", document_type="personal_note", metadata_={"existing": True})
        db.add(doc)
        db.flush()
        chunk = KnowledgeChunk(tenant_id=tid, knowledge_document_id=doc.id, chunk_index=0, content="PRIVATE-SOURCE", token_count=2)
        job = ProcessingJob(tenant_id=tid, job_type="knowledge_principle_extraction", entity_type="knowledge_document", entity_id=doc.id, status="queued", result={})
        db.add_all([chunk, job])
        db.commit()
        doc_id, job_id = doc.id, job.id

    response = LLMResponse(message=Message("assistant", invalid_text), usage=Usage(input_tokens=10, output_tokens=20, total_tokens=30), model="test-model", provider="test", finish_reason="length")
    calls = []

    async def complete(request):
        calls.append(request)
        return response

    provider = SimpleNamespace(name="hy4-go-zero" if hy4_mode else "test", complete=complete)
    service = kls.KnowledgeLibraryService(provider)
    real_parse = kls.parse_json_response
    observed = []

    def parse_after_record(text):
        # The row must be pending BEFORE parsing, not just after the exception.
        assert any(isinstance(row, BudgetUsage) and row.token_count == 30 for row in active[0].new)
        return real_parse(text)

    active = []

    def session(*args):
        db = Session(engine, expire_on_commit=False)
        db.info["tenant_id"] = tid
        active[:] = [db]
        return db

    def error_handler(actor, exc, **context):
        observed.append(exc)
        return {"status": "error"}

    monkeypatch.setattr(kls, "parse_json_response", parse_after_record)
    monkeypatch.setattr(kls.BudgetController, "can_spend", lambda *args: True)
    monkeypatch.setattr(kls, "KnowledgeLibraryService", lambda: service)
    monkeypatch.setattr(workers, "_session", session)
    monkeypatch.setattr(workers, "_handle_actor_error", error_handler)
    assert workers.extract_knowledge_principles.fn(job_id, tenant_id=tid) == {"status": "error"}
    assert len(calls) == 1
    assert len(observed) == 1
    exc = observed[0]
    assert isinstance(exc, StructuredOutputError if invalid_text == "not JSON" else ValueError)

    # A new session proves persistence across the actor's rollback and close.
    with Session(engine) as db:
        db.info["tenant_id"] = tid
        usage = db.scalars(select(BudgetUsage)).all()
        assert len(usage) == 1
        assert usage[0].token_count == 30
        assert usage[0].workflow == "investment_principles"
        assert usage[0].cost_eur == 0 if hy4_mode else usage[0].cost_eur > 0
        doc = db.get(KnowledgeDocument, doc_id)
        assert doc.metadata_["existing"] is True
        assert doc.metadata_.get("hy4_principle_run_state") == ("blocked" if hy4_mode else None)
        job = db.get(ProcessingJob, job_id)
        assert job.status == "failed"
        assert job.completed_at is not None
        assert "lote 1/1" in job.error
        assert job.result == {"error_diagnostic": exc.diagnostic}
        assert "PRIVATE-SOURCE" not in repr(job.result)
        assert invalid_text not in repr(job.result)
        assert job.result["error_diagnostic"]["output_tokens"] == 20
        if hy4_mode:
            with pytest.raises(ProviderDisabledError):
                asyncio.run(service.extract_principle_batches(db, doc))
            assert len(calls) == 1
    engine.dispose()
