"""N+1 en _vector_library_context: los chunks RAG se hidratan en lote.

Cada hit de Qdrant costaba una consulta (chunk + documento) en el camino
de las preguntas de biblioteca del Cerebro; con 10-20 candidatos eran
10-20 consultas por pregunta. Ahora una sola consulta por tanda con los
mismos filtros (tenant, documento ready), mismo orden y mismo cap.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument, Tenant
from app.models.entities import Base
from app.services.library_context import _vector_library_context
from app.services.rag import RAGIndex


def _session(chunk_count: int = 12):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="lib-count", name="Test")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    document = KnowledgeDocument(
        title="Carta", author="Autor", document_type="fund_letter",
        source_url="https://example.org/c", status="ready", language="en",
    )
    db.add(document)
    db.flush()
    chunks = []
    for i in range(chunk_count):
        chunk = KnowledgeChunk(
            knowledge_document_id=document.id, chunk_index=i,
            content=f"Pasaje {i} sobre asignacion de capital.",
            qdrant_point_id=f"point-{i}", page_number=i + 1,
        )
        db.add(chunk)
        chunks.append(chunk)
    db.commit()
    return db, engine, chunks


def test_vector_library_context_hydrates_chunks_in_one_query(monkeypatch):
    db, engine, chunks = _session()
    hits = [
        {"entity_type": "knowledge_chunk", "entity_id": chunk.id, "point_id": f"point-{i}"}
        for i, chunk in enumerate(chunks)
    ]
    monkeypatch.setattr(RAGIndex, "search", lambda *a, **k: hits)
    statements = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        contexts = _vector_library_context(db, "asignacion de capital", limit=12, tenant_id=db.info["tenant_id"])
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert len(contexts) == 12
    assert [c["chunk_id"] for c in contexts] == [c.id for c in chunks]
    assert len(statements) <= 1, f"{len(statements)} sentencias para 12 chunks"


def test_chat_rag_chunks_hydrate_in_one_query(monkeypatch):
    """_rag_chunks del Cerebro: lote, no una consulta por hit."""
    from app.models import Document, DocumentChunk
    from app.services.chat_service import ChatService

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="rag-count", name="Test")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    document = Document(title="10-K", source_type="SEC", source_url="https://sec.gov/x")
    db.add(document)
    db.flush()
    chunks = []
    for i in range(6):
        chunk = DocumentChunk(
            document_id=document.id, chunk_index=i, text=f"Pasaje {i} del 10-K.",
            token_count=10, qdrant_point_id=f"dp-{i}",
        )
        db.add(chunk)
        chunks.append(chunk)
    db.commit()
    hits = [
        {"entity_type": "document_chunk", "entity_id": chunk.id, "point_id": f"dp-{i}"}
        for i, chunk in enumerate(chunks)
    ]
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_CHAT", "1")
    monkeypatch.setattr(RAGIndex, "search", lambda *a, **k: hits)
    statements = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        rows = ChatService()._rag_chunks(db, "deuda neta", None)
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert [row["entity_id"] for row in rows] == [c.id for c in chunks]
    assert len(statements) <= 1, f"{len(statements)} sentencias para 6 chunks"
