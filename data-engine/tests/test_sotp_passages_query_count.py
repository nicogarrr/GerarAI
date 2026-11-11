"""Batch SOTP passages without changing Python's Unicode/whitespace matching."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document, DocumentChunk, Tenant
from app.services.expert_team import sotp_valuer as svc
from app.services.expert_team.models import RunContext, ToolOutput


def _fixture(n):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    db.add(Tenant(id=1, external_id="sotp-perf"))
    db.flush()
    db.info["tenant_id"] = 1
    company = Company(ticker="PERF", name="Perf", exchange="TEST", currency="USD",
                      company_type="operating", valuation_model="unassigned")
    db.add(company)
    db.flush()
    docs = []
    for i in range(n):
        doc = Document(company_id=company.id, tenant_id=1, title=f"Doc {i}",
                       source_type="SEC", source_url=f"https://example.test/{i}",
                       published_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i))
        db.add(doc)
        db.flush()
        docs.append(doc)
        # First match is deliberately late. SQL lower() is not Python casefold().
        for j in range(15):
            text = "irrelevant" if j < 10 else f"Straße\u00a0  signal {i}:{j} " + "x" * 1600
            db.add(DocumentChunk(tenant_id=1, document_id=doc.id, chunk_index=j, text=text))
    db.commit()
    return engine, db, docs


def _run(db):
    return svc.passages_tool(db, "test", ("strasse signal",), "test").fn(
        RunContext(tenant_id=1, ticker="PERF"))


def test_queries_flat_and_no_chunk_orm_hydration():
    counts = []
    for n in (1, 8):
        engine, db, _ = _fixture(n)
        statements, loaded = [], []
        def on_sql(*a):
            statements.append(a[2])
        def on_load(*a):
            loaded.append(1)
        event.listen(engine, "before_cursor_execute", on_sql)
        event.listen(DocumentChunk, "load", on_load)
        try:
            out = _run(db)
            counts.append(len(statements))
            assert len(out) == 3 * n
            assert loaded == []
        finally:
            event.remove(DocumentChunk, "load", on_load)
            event.remove(engine, "before_cursor_execute", on_sql)
            db.close()
            engine.dispose()
    assert counts == [3, 3], counts


def test_exact_parity_with_previous_per_document_reader():
    engine, db, docs = _fixture(10)
    try:
        expected = []
        for doc in reversed(docs[-svc.PASSAGE_DOCUMENTS:]):
            chunks = db.scalars(select(DocumentChunk).where(
                DocumentChunk.tenant_id == 1, DocumentChunk.document_id == doc.id
            ).order_by(DocumentChunk.chunk_index)).all()
            hits = [c for c in chunks if "strasse signal" in " ".join(c.text.split()).casefold()]
            for ch in hits[:svc.PASSAGES_PER_DOC]:
                expected.append(ToolOutput(source={
                    "table": "document_chunks", "document_id": str(doc.id),
                    "title": doc.title, "url": doc.source_url,
                    "date": doc.published_at.date().isoformat(),
                }, data={"text": ch.text[:1500]}))
        assert _run(db) == expected
    finally:
        db.close()
        engine.dispose()


def test_existing_documents_without_chunks():
    engine, db, _ = _fixture(1)
    try:
        db.query(DocumentChunk).delete()
        db.commit()
        assert _run(db) == []
    finally:
        db.close()
        engine.dispose()
