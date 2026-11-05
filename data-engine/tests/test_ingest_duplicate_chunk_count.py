"""La via de duplicado cuenta los chunks en SQL, sin hidratarlos.

Antes (5-nov-2026): ``len(duplicate.chunks)`` cargaba TODAS las filas de
document_chunks del documento duplicado (texto completo incluido) solo para
contarlas: memoria del worker y una consulta pesada por reintento de ingesta.
Ahora es un COUNT. Determinista: se espian las sentencias SQL emitidas y se
exige que ninguna seleccione la columna de texto de los chunks.
"""

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Company, DocumentChunk
from app.services.document_ingestion_service import DocumentIngestionService

CONTENT = (
    b"La disciplina de margen operativo y la demanda de IA son evidencia "
    b"central de la tesis. " * 40
)


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = "tenant-test"
    company = Company(
        ticker="AAPL", name="Apple Inc.", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", cik="0000320193", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    session.add(company)
    session.commit()
    return engine, session


def _ingest(db):
    return DocumentIngestionService().ingest_bytes(
        db,
        ticker="AAPL",
        title="Nota AAPL",
        content=CONTENT,
        filename="aapl-nota.txt",
        source_type="test_upload",
    )


def test_duplicado_cuenta_chunks_sin_hidratar_el_texto():
    engine, db = _session()
    first = _ingest(db)
    assert first["status"] == "ingested"
    real = db.scalar(
        select(func.count(DocumentChunk.id)).where(
            DocumentChunk.document_id == first["document_id"]
        )
    )
    assert real >= 1

    statements: list[str] = []

    def spy(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", spy)
    try:
        duplicate = _ingest(db)
    finally:
        event.remove(engine, "before_cursor_execute", spy)

    assert duplicate["status"] == "duplicate"
    assert duplicate["chunks"] == real
    # Ninguna consulta del camino duplicado trae el texto de los chunks:
    # el unico SELECT sobre document_chunks permitido es el COUNT.
    chunk_reads = [s for s in statements if "from document_chunks" in s]
    assert chunk_reads, "el dedup debe contar los chunks existentes"
    for s in chunk_reads:
        assert "document_chunks.text" not in s, s
        assert "count(" in s, s
