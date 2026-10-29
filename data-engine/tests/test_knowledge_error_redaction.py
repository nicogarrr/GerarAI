"""El texto de una excepción guardado para la UI de conocimiento va redactado.

Ronda 3 (fuzzing con sonda de fugas en respuestas 2xx): el error de extracción
de la biblioteca y el ``error`` de una fuente RAG fallida se guardaban como
``f"{type(exc).__name__}: {exc}"`` sin redactar y la API los devuelve tal cual.
Un error de httpx lleva la URL del proveedor, con ``?apikey=`` incluida.
"""
from __future__ import annotations

from uuid import uuid4

from app.core.database import SessionLocal, init_db
from app.models import KnowledgeRagSource, Tenant
from app.services.knowledge_library_service import extraction_error_message
from app.services.knowledge_rag.ingest import mark_failed

KEY = "sk-live-0123456789abcdefSECRET"
RAW = f"Client error '401' for url 'https://api.provider.test/v1/embed?apikey={KEY}&q=x'"


def test_library_extraction_error_is_redacted():
    message = extraction_error_message(RuntimeError(RAW))
    assert KEY not in message
    assert message.startswith("RuntimeError")


def test_rag_source_failure_reason_is_redacted():
    init_db()
    with SessionLocal() as db:
        tenant = Tenant(external_id=f"rag-redact-{uuid4().hex[:8]}")
        db.add(tenant)
        db.commit()
        db.info["tenant_id"] = tenant.id
        source = KnowledgeRagSource(**_source_fields(tenant.id))
        db.add(source)
        db.commit()
        mark_failed(db, source.id, f"HTTPStatusError: {RAW}")
        db.expire_all()
        stored = db.get(KnowledgeRagSource, source.id)
        assert stored.status == "failed"
        assert KEY not in stored.error
        assert "HTTPStatusError" in stored.error


def _source_fields(tenant_id: int) -> dict:
    from sqlalchemy import inspect

    fields: dict = {"tenant_id": tenant_id}
    for column in inspect(KnowledgeRagSource).columns:
        if column.primary_key or column.nullable or column.default is not None or column.server_default is not None:
            continue
        if column.name in fields:
            continue
        python_type = column.type.python_type
        fields[column.name] = (f"x-{uuid4().hex[:8]}" if python_type is str else 0 if python_type is int
                               else {} if python_type is dict else None)
    return fields
