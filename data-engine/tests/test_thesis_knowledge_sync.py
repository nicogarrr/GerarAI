"""La aprobacion de una tesis la indexa como conocimiento (y lo retira).

Sin red: la ingesta usa el almacen local de APP_ENV=test y el provider LLM
de prueba no se llega a usar (la ingesta no extrae principios).
"""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models import Company, KnowledgeChunk, KnowledgeCollection, KnowledgeDocument, ThesisVersion
from app.services.thesis_approval_service import apply_approval_decision


@pytest.fixture
def db_thesis():
    init_db()
    db = SessionLocal()
    ticker = f"K{uuid4().hex[:8].upper()}"
    company = Company(
        ticker=ticker,
        name="Knowledge Sync Test",
        exchange="TEST",
        currency="USD",
        sector="Technology",
        industry="Software",
        company_type="operating_company",
        valuation_model="standard_dcf",
        factor_tags=["software"],
    )
    db.add(company)
    db.flush()
    thesis = ThesisVersion(
        company_id=company.id,
        version=1,
        status="final",
        thesis_markdown="# Tesis",
        executive_summary="Resumen ejecutivo de prueba con contenido suficiente.",
        rating="watch",
        hypothesis="Hipotesis de prueba con texto suficiente para la ingesta.",
    )
    db.add(thesis)
    db.commit()
    db.refresh(thesis)
    try:
        yield db, company, thesis
    finally:
        db.close()


def _auto_docs(db, ticker):
    return list(
        db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.metadata_["auto"].as_string() == "thesis",
                KnowledgeDocument.metadata_["ticker"].as_string() == ticker,
            )
        ).all()
    )


def test_approve_indexes_thesis_as_knowledge(db_thesis):
    db, company, thesis = db_thesis
    apply_approval_decision(db, thesis.id, "approve", via="test")
    docs = _auto_docs(db, company.ticker)
    assert len(docs) == 1
    assert docs[0].document_type == "own_thesis"
    collection = db.get(KnowledgeCollection, docs[0].collection_id)
    assert collection is not None
    assert collection.name == "Tesis publicadas"
    chunks = list(
        db.scalars(
            select(KnowledgeChunk).where(
                KnowledgeChunk.knowledge_document_id == docs[0].id
            )
        ).all()
    )
    assert chunks, "la tesis publicada debe quedar fragmentada para el RAG"


def test_reject_published_removes_knowledge(db_thesis):
    db, company, thesis = db_thesis
    apply_approval_decision(db, thesis.id, "approve", via="test")
    assert len(_auto_docs(db, company.ticker)) == 1
    apply_approval_decision(db, thesis.id, "reject", via="test")
    assert _auto_docs(db, company.ticker) == []


def test_new_version_replaces_previous_document(db_thesis):
    db, company, thesis = db_thesis
    apply_approval_decision(db, thesis.id, "approve", via="test")
    newer = ThesisVersion(
        company_id=company.id,
        version=2,
        status="final",
        thesis_markdown="# Tesis v2",
        executive_summary="Resumen ejecutivo renovado con contenido suficiente.",
        rating="watch",
        hypothesis="Hipotesis renovada con texto suficiente para la ingesta.",
    )
    db.add(newer)
    db.commit()
    db.refresh(newer)
    apply_approval_decision(db, newer.id, "approve", via="test")
    docs = _auto_docs(db, company.ticker)
    assert len(docs) == 1
    assert docs[0].metadata_["thesis_version_id"] == newer.id


def test_reject_unpublished_keeps_older_published_document(db_thesis):
    db, company, thesis = db_thesis
    apply_approval_decision(db, thesis.id, "approve", via="test")
    newer = ThesisVersion(
        company_id=company.id,
        version=2,
        status="final",
        thesis_markdown="# Tesis v2",
        executive_summary="Otro resumen de prueba con contenido suficiente.",
        rating="watch",
    )
    db.add(newer)
    db.commit()
    db.refresh(newer)
    apply_approval_decision(db, newer.id, "reject", via="test")
    docs = _auto_docs(db, company.ticker)
    assert len(docs) == 1
    assert docs[0].metadata_["thesis_version_id"] == thesis.id
