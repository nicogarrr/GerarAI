"""Doctrina por texto SQL cuando el vectorial esta apagado o no trae al autor."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument
from app.models.entities import Base
from app.services.library_context import retrieve_library_context
from app.services.rag import RAGIndex

DOCS = [
    ("Warren Buffett", "Berkshire 2015", "Patience is a virtue: we wait for fat pitches and the investor must have patience."),
    ("Warren Buffett", "Berkshire 2010", "Our debt is used sparingly. Leverage can ruin a good business in a cyclical downturn."),
    ("Warren Buffett", "Berkshire 2012", "Share repurchases make sense only below intrinsic value."),
    ("Howard Marks", "Memo 2019", "Risk means more things can happen than will happen. Margin of safety matters."),
    ("Numantia", "Carta 2020", "Patience and long term thinking guide our capital allocation. Debt must be low."),
]
QUESTIONS = [
    ("¿Qué dicen las cartas de Buffett sobre la paciencia?", "buffett"),
    ("¿Qué opina Buffett de la deuda y el apalancamiento?", "buffett"),
    ("¿Cuándo recompra acciones Buffett según sus cartas?", "buffett"),
    ("¿Qué dice Howard Marks sobre el riesgo?", "marks"),
    ("Según Marks, ¿qué es el margen de seguridad?", "marks"),
    ("¿Qué dicen las cartas de Buffett sobre la deuda?", "buffett"),
    ("Doctrina de Buffett sobre recompras de acciones", "buffett"),
    ("Cartas de Marks: riesgo y margen de seguridad", "marks"),
    ("Biblioteca: paciencia y largo plazo", None),
    ("Buffett y la paciencia en las cartas", "buffett"),
]


@pytest.fixture()
def db():
    session = Session(create_engine("sqlite://"))
    Base.metadata.create_all(session.get_bind())
    for author, title, text in DOCS:
        doc = KnowledgeDocument(tenant_id=1, title=title, author=author, document_type="fund_letter", status="ready")
        session.add(doc)
        session.flush()
        session.add(KnowledgeChunk(tenant_id=1, knowledge_document_id=doc.id, chunk_index=0, content=text, page_number=1))
    session.commit()
    session.info["tenant_id"] = 1
    return session


@pytest.mark.parametrize(("question", "author"), QUESTIONS)
def test_named_author_gets_own_fragments_without_vector(db, question, author):
    rows = retrieve_library_context(db, question, vector=False)
    assert rows, question
    if author:
        assert any(author in str(r["author"]).lower() for r in rows)
        assert all(author in str(r["author"]).lower() for r in rows)


def test_author_fragments_first_when_vector_returns_other_authors(db, monkeypatch):
    other = db.query(KnowledgeChunk).join(KnowledgeDocument).filter(KnowledgeDocument.author == "Numantia").one()
    other.qdrant_point_id = "p"
    db.commit()
    monkeypatch.setattr(RAGIndex, "search", lambda *a, **k: [
        {"entity_type": "knowledge_chunk", "entity_id": other.id, "point_id": "p"}])
    rows = retrieve_library_context(db, "¿Qué dicen las cartas de Buffett sobre la paciencia?")
    assert "buffett" in str(rows[0]["author"]).lower()


def test_no_terms_or_wrong_tenant_returns_nothing(db):
    assert retrieve_library_context(db, "hola", vector=False) == []
    db.info["tenant_id"] = 2
    assert retrieve_library_context(db, "Buffett paciencia", vector=False) == []
