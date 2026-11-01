"""Chat: «¿qué documentos tengo en la biblioteca?» lista tus documentos guardados.

Antes la pregunta iba a la recuperación por contenido o a la respuesta general,
sin decir qué hay. Ahora cuenta tus documentos por tipo y lista los últimos.
Solo lectura y solo tu tenant.
"""

import asyncio
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Base, KnowledgeDocument
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"

    async def complete(self, *a, **k):
        raise AssertionError("la lista de documentos no debe pasar por el LLM")


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    docs = {1: (("Carta 2024 a accionistas", "letter", date(2025, 2, 22), None),
                ("10-K Microsoft 2025", "filing", date(2025, 7, 30), "MSFT"),
                ("Notas sobre Coca-Cola", "note", date(2026, 10, 1), "KO"),
                ("Borrador roto", "note", None, None)),
            2: (("Secreto de B", "note", date(2026, 1, 1), "AAPL"),)}
    for tenant, rows in docs.items():
        db.info["tenant_id"] = tenant
        for title, kind, published, ticker in rows:
            db.add(KnowledgeDocument(tenant_id=tenant, title=title, document_type=kind, publication_date=published,
                                     ticker=ticker, status="failed" if title == "Borrador roto" else "ready"))
        db.commit()
    db.info["tenant_id"] = 1
    return db


def _ask(db, question):
    return asyncio.run(ChatService(provider=_NoLLM()).answer(db, question, "global", None))


@pytest.mark.parametrize("question", ["¿Qué documentos tengo en la biblioteca?", "mis documentos",
                                      "¿Cuántos documentos tengo?"])
def test_lists_documents(question):
    resp = _ask(_db(), question)
    assert resp.llm_trace.get("path") == "account_documents"
    assert resp.answer.startswith("Tienes 3 documentos en la biblioteca (filing 1, letter 1, note 1). Los últimos:")
    assert "- «Notas sobre Coca-Cola» (KO, 1 oct 2026)" in resp.answer
    assert "- «Carta 2024 a accionistas» (22 feb 2025)" in resp.answer
    assert "Borrador roto" not in resp.answer
    assert resp.answer.endswith("Para abrirlos o subir más, ve a Biblioteca.")


def test_no_documents():
    db = _db()
    db.info["tenant_id"] = 3
    resp = _ask(db, "mis documentos")
    assert resp.answer.startswith("No tienes documentos en la biblioteca. Puedes subirlos en Biblioteca.")


def test_user_b_never_sees_user_a():
    db = _db()
    db.info["tenant_id"] = 2
    resp = _ask(db, "mis documentos")
    assert "Secreto de B" in resp.answer and "Coca-Cola" not in resp.answer and "Microsoft" not in resp.answer


def test_english(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        db = _db()
        db.info["language"] = "en"
        resp = _ask(db, "What documents do I have?")
        assert resp.answer.startswith("You have 3 documents in the library (filing 1, letter 1, note 1). Latest:")
        assert "- «Notas sobre Coca-Cola» (KO, Oct 1, 2026)" in resp.answer
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("question", ["¿Qué dice Buffett sobre los recompras?", "documentos de MSFT",
                                      "¿Qué documentos necesito para Hacienda?"])
def test_other_questions_unchanged(question):
    resp = _ask(_db(), question)
    assert (resp.llm_trace or {}).get("path") != "account_documents"
