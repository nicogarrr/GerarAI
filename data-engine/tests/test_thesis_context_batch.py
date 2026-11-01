"""retrieve_thesis_context hidrataba cada chunk RAG con su propia consulta
(hasta 5 por llamada). Ahora una sola consulta con IN, manteniendo el orden
de los hits y todos los filtros de tenant/empresa."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models import Company, Document, DocumentChunk, Tenant
from app.models.entities import Base
from app.services import thesis_context


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="t-batch", name="t")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    company = Company(ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ",
                      currency="USD", sector="Telecom", industry="Sat",
                      company_type="growth", valuation_model="unassigned",
                      special_sources=[], special_risks=[], factor_tags=[])
    db.add(company)
    db.flush()
    return db, engine, company


def _chunk(db, company, title, text):
    doc = Document(company_id=company.id, title=title, source_type="sec_filing",
                   source_url=f"https://example.org/{title}")
    db.add(doc)
    db.flush()
    chunk = DocumentChunk(document_id=doc.id, chunk_index=0, text=text)
    db.add(chunk)
    db.flush()
    return chunk


def test_hydrates_chunks_in_one_query_preserving_hit_order(monkeypatch):
    db, engine, company = _session()
    c1 = _chunk(db, company, "10-K", "riesgos regulatorios")
    c2 = _chunk(db, company, "10-Q", "resultados trimestrales")
    c3 = _chunk(db, company, "8-K", "evento material")
    db.commit()

    hits = [
        {"entity_type": "document_chunk", "entity_id": c3.id},
        {"entity_type": "document_chunk", "entity_id": c1.id},
        {"entity_type": "document_chunk", "entity_id": c2.id},
        {"entity_type": "document_chunk", "entity_id": c3.id},  # duplicado
        {"entity_type": "document_chunk", "entity_id": 99999},  # inexistente
        {"entity_type": "knowledge_chunk", "entity_id": c1.id},  # otro tipo
    ]
    monkeypatch.setattr(thesis_context.RAGIndex, "search", lambda self, q, **kw: hits)
    monkeypatch.setattr(thesis_context, "retrieve_library_context", lambda db, q: [])

    statements = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        if "FROM document_chunks JOIN documents" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        context = thesis_context.retrieve_thesis_context(db, company)
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert [c["text"] for c in context] == [
        "evento material", "riesgos regulatorios", "resultados trimestrales",
    ]
    assert len(statements) == 1, f"{len(statements)} consultas de hidratacion para 3 chunks"
