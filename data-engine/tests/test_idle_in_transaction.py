"""Regresion: ninguna espera larga (LLM/red) con la sesion idle in transaction.

Cubierto:
- workers.dramatiq_app._session: el SELECT del tenant commitea antes de
  devolver la sesion (los actores no arrancan con una tx abierta).
- KnowledgeLibraryService.extract_principle_batches: la transaccion de
  lectura se cierra antes de cada `await provider.complete(...)`.
"""

import asyncio
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument, Tenant
from app.models.entities import Base


def _db():
    db = Session(create_engine("sqlite://"))
    Base.metadata.create_all(db.get_bind())
    db.info["tenant_id"] = 1
    return db


def test_worker_session_does_not_start_in_transaction(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as setup:
        setup.add(Tenant(id=1, external_id="t", status="active"))
        setup.commit()

    from app.core import database
    from app.workers import dramatiq_app

    monkeypatch.setattr(database, "SessionLocal", lambda: Session(engine, expire_on_commit=False))
    db = dramatiq_app._session(1, "user-1")
    try:
        assert not db.in_transaction()
        # El tenant sigue siendo legible tras el commit (expire_on_commit=False
        # en produccion; aqui lo forzamos a mano para el mismo contrato).
        assert db.info["tenant_id"] == 1
    finally:
        db.close()


def test_principle_extraction_commits_before_llm_await():
    from app.services.knowledge_library_service import KnowledgeLibraryService

    db = _db()
    doc = KnowledgeDocument(
        tenant_id=1, title="Buffett", author="Buffett",
        document_type="fund_letter", status="ready",
    )
    db.add(doc)
    db.flush()
    for i in range(2):
        db.add(KnowledgeChunk(
            tenant_id=1, knowledge_document_id=doc.id, chunk_index=i,
            content=f"Repurchases add value at sensible prices. Part {i}.",
            page_number=i + 1,
        ))
    db.commit()

    class Usage:
        input_tokens = 10
        output_tokens = 5
        total_tokens = 15

    class Response:
        text = json.dumps({"principles": []})
        model = "fake-model"
        usage = Usage()

    class GuardProvider:
        """Fallara si la sesion llega a complete() con una tx abierta."""

        name = "fake"

        async def complete(self, request):
            assert not db.in_transaction(), (
                "await del LLM con la sesion idle in transaction"
            )
            return Response()

    service = KnowledgeLibraryService(provider=GuardProvider())
    result = asyncio.run(service.extract_principle_batches(db, doc))
    assert result["batches_processed"] >= 1
    db.close()
