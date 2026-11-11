"""Analyst evidence keeps Python matching while batching document reads."""
import asyncio
from datetime import date

from sqlalchemy import event, select

from app.models.entities import DocumentChunk
from app.services.expert_team import analyst_blend as svc
from app.services.expert_team.models import RunContext, ToolOutput
from tests.test_sotp_passages_query_count import _fixture


def _run(db):
    tool = svc.analyst_passages_tool(db, ["strasse signal"], today=date(2026, 1, 1))
    return asyncio.run(tool.fn(RunContext(tenant_id=1, ticker="PERF")))


def test_analyst_queries_flat_and_zero_chunk_orm():
    counts = []
    for n in (1, 8):
        engine, db, _ = _fixture(n)
        statements, loads = [], []
        def on_sql(*args):
            statements.append(args[2])
        def on_load(*args):
            loads.append(1)
        event.listen(engine, "before_cursor_execute", on_sql)
        event.listen(DocumentChunk, "load", on_load)
        try:
            assert len(_run(db)) == n * svc.DOC_MAX_PASSAGES_PER_DOC
            counts.append(len(statements))
            assert loads == []
        finally:
            event.remove(DocumentChunk, "load", on_load)
            event.remove(engine, "before_cursor_execute", on_sql)
            db.close()
            engine.dispose()
    assert counts == [4, 4], counts


def test_analyst_exact_parity_with_previous_reader():
    engine, db, docs = _fixture(8)
    try:
        expected = []
        for doc in reversed(docs):
            chunks = db.scalars(select(DocumentChunk).where(
                DocumentChunk.tenant_id == 1, DocumentChunk.document_id == doc.id
            ).order_by(DocumentChunk.chunk_index)).all()
            hits = [c for c in chunks if svc._mentions(c.text, ["strasse signal"])]
            for c in hits[:svc.DOC_MAX_PASSAGES_PER_DOC]:
                expected.append(ToolOutput(source={
                    "table": "document_chunks", "document_id": str(doc.id),
                    "title": doc.title, "url": doc.source_url, "source_type": doc.source_type,
                    "date": doc.published_at.date().isoformat(),
                }, data={"text": c.text[:svc.DOC_PASSAGE_CHARS]}))
        assert _run(db) == expected
    finally:
        db.close()
        engine.dispose()


def test_analyst_documents_without_chunks():
    engine, db, _ = _fixture(1)
    try:
        db.query(DocumentChunk).delete()
        db.commit()
        assert _run(db) == []
    finally:
        db.close()
        engine.dispose()
