"""Bordes de universal_search_service (US1): guards de puntuacion y filtros,
rama PostgreSQL de _fts, hidratacion de candidatos vectoriales y dedup RRF.

Sin red: la busqueda vectorial se dobla con una RAGIndex falsa (no hay Qdrant
real) y ninguna llamada toca Redis (search no escribe en BBDD). BBDD: SQLite
real en memoria con fixtures literales. La rama 535 (thesis_section) NO se
cubre: la tesis esta fuera de las zonas permitidas del bucle; se declara.
Acotacion SQLite: _fts solo anade el WHERE tsvector cuando el dialecto es
postgresql, asi que en SQLite los candidatos lexicos no se filtran por texto;
la rama postgres se prueba con un dialecto doblado, sin servidor real.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    DecisionJournalEntry,
    Document,
    DocumentChunk,
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeDocument,
    Tenant,
)
from app.models.entities import Base, InvestmentCaseStudy
from app.services.universal_search_service import (
    SearchCandidate,
    UniversalSearchService,
    _lexical_score,
)


def _candidato(**kwargs) -> SearchCandidate:
    kwargs.setdefault("key", "document_chunk:1")
    kwargs.setdefault("entity_type", "document_chunk")
    kwargs.setdefault("entity_id", 1)
    kwargs.setdefault("title", "Informe anual")
    kwargs.setdefault("text", "Texto del informe")
    return SearchCandidate(**kwargs)


# --------------------------------------------------------- helpers puros (directos)


def test_lexical_score_sin_tokens() -> None:
    # TOKEN_RE exige mas de un caracter: "a b" no deja tokens.
    assert _lexical_score("a b", _candidato()) == 0.0


def test_lexical_score_sin_coincidencia() -> None:
    assert _lexical_score("zzz", _candidato()) == 0.0


def test_vector_key_incompleta() -> None:
    assert UniversalSearchService._vector_key({}) == ""  # noqa: SLF001
    assert UniversalSearchService._vector_key({"entity_type": "document_chunk"}) == ""  # noqa: SLF001


def test_matches_filters_source_type() -> None:
    candidato = _candidato(source_type="news")
    assert (
        UniversalSearchService._matches_filters(  # noqa: SLF001
            candidato, source_types={"sec_filing"}, statuses=None, date_from=None, date_to=None
        )
        is False
    )


def test_matches_filters_status() -> None:
    candidato = _candidato(status="draft")
    assert (
        UniversalSearchService._matches_filters(  # noqa: SLF001
            candidato, source_types=None, statuses={"approved"}, date_from=None, date_to=None
        )
        is False
    )


def test_matches_filters_date_from_sin_fecha() -> None:
    candidato = _candidato(as_of=None)
    assert (
        UniversalSearchService._matches_filters(  # noqa: SLF001
            candidato, source_types=None, statuses=None, date_from=date(2024, 1, 1), date_to=None
        )
        is False
    )


def test_matches_filters_date_from_anterior() -> None:
    candidato = _candidato(as_of=date(2023, 12, 31))
    assert (
        UniversalSearchService._matches_filters(  # noqa: SLF001
            candidato, source_types=None, statuses=None, date_from=date(2024, 1, 1), date_to=None
        )
        is False
    )


def test_matches_filters_date_to_con_datetime() -> None:
    # as_of como datetime se convierte a date antes de comparar.
    candidato = _candidato(as_of=datetime(2024, 6, 1, 12, 0, 0))
    assert (
        UniversalSearchService._matches_filters(  # noqa: SLF001
            candidato, source_types=None, statuses=None, date_from=None, date_to=date(2024, 5, 31)
        )
        is False
    )


def test_fts_solo_filtra_en_postgresql() -> None:
    consulta = select(DecisionJournalEntry)
    postgres = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    con_fts = UniversalSearchService._fts(consulta, DecisionJournalEntry.rationale, "capex", postgres)  # noqa: SLF001
    assert "websearch_to_tsquery" in str(con_fts)
    assert "@@" in str(con_fts)
    sqlite = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    sin_fts = UniversalSearchService._fts(consulta, DecisionJournalEntry.rationale, "capex", sqlite)  # noqa: SLF001
    assert "@@" not in str(sin_fts)


# ------------------------------------------------------------------- fixtures DB


@pytest.fixture
def db_tenant():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id="tenant-us-bordes", name="Tenant US Bordes")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id
        yield db, tenant.id


def _empresa(db: Session, ticker: str = "AAA") -> Company:
    company = Company(
        ticker=ticker,
        name="Empresa AAA",
        exchange="TEST",
        currency="EUR",
        sector="Industrials",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _documento_con_chunk(db: Session, company: Company) -> DocumentChunk:
    filing = Document(
        company_id=company.id,
        title="2025 annual filing",
        source_type="annual_report",
        source_url="https://example.com/filing",
    )
    db.add(filing)
    db.flush()
    chunk = DocumentChunk(document_id=filing.id, chunk_index=0, text="termino repetido termino")
    db.add(chunk)
    db.flush()
    return chunk


def _knowledge_con_chunk(
    db: Session, status: str = "active"
) -> tuple[KnowledgeChunk, KnowledgeDocument, KnowledgeCollection]:
    collection = KnowledgeCollection(name="Coleccion bordes", slug="bordes")
    db.add(collection)
    db.flush()
    document = KnowledgeDocument(
        title="Documento bordes",
        document_type="personal_note",
        collection_id=collection.id,
        status=status,
    )
    db.add(document)
    db.flush()
    chunk = KnowledgeChunk(
        knowledge_document_id=document.id, chunk_index=0, content="termino suelto", page_number=3
    )
    db.add(chunk)
    db.flush()
    return chunk, document, collection


# ----------------------------------------------------------------- guards search


def test_search_sin_tenant(db_tenant) -> None:
    db, _tid = db_tenant
    db.info.pop("tenant_id")  # sesion desechada al cerrar el test
    with pytest.raises(ValueError) as excinfo:
        UniversalSearchService().search(db, "capex")
    assert str(excinfo.value) == "Tenant context is required for universal search"


def test_search_query_vacia(db_tenant) -> None:
    db, _tid = db_tenant
    with pytest.raises(ValueError) as excinfo:
        UniversalSearchService().search(db, "   ")
    assert str(excinfo.value) == "Search query cannot be empty"


def test_principle_candidates_tipo_no_permitido(db_tenant) -> None:
    db, _tid = db_tenant
    assert (
        UniversalSearchService()._principle_candidates(db, "capex", None, {"document_chunk"}, None)  # noqa: SLF001
        == []
    )


# ------------------------------------------------------------------- hidratacion


def test_case_candidates_hidrata_caso(db_tenant) -> None:
    db, _tid = db_tenant
    collection = KnowledgeCollection(name="Casos", slug="casos")
    db.add(collection)
    db.flush()
    caso = InvestmentCaseStudy(
        title="Caso bordes",
        summary="Resumen del caso",
        outcome="Desenlace del caso",
        lessons=["leccion uno", "leccion dos"],
        collection_id=collection.id,
        status="approved",
        period="2010-2012",
        sector="Utilities",
    )
    db.add(caso)
    db.flush()
    resultado = UniversalSearchService()._case_candidates(db, "caso", None, None, None)  # noqa: SLF001
    assert len(resultado) == 1
    candidato = resultado[0]
    assert candidato.key == f"investment_case:{caso.id}"
    assert candidato.entity_type == "investment_case"
    assert candidato.title == "Caso bordes"
    assert candidato.text == "Resumen del caso Desenlace del caso leccion uno leccion dos"
    assert candidato.collection == "Casos"
    assert candidato.status == "approved"
    assert candidato.metadata == {"period": "2010-2012", "sector": "Utilities"}


def test_hydrate_descarta_rows_invalidas(db_tenant) -> None:
    db, _tid = db_tenant
    rows = [
        {"entity_type": "investment_case", "entity_id": 1},  # tipo no hidratable
        {"entity_type": "document_chunk", "entity_id": "no-entero"},  # id no int
        {"entity_type": "knowledge_chunk", "entity_id": 1},  # tipo no permitido
    ]
    assert (
        UniversalSearchService()._hydrate_vector_candidates(  # noqa: SLF001
            db, rows, company=None, entity_types={"document_chunk"}, collection_id=None
        )
        == []
    )


def test_hydrate_knowledge_chunk_con_coleccion(db_tenant) -> None:
    db, _tid = db_tenant
    chunk, document, collection = _knowledge_con_chunk(db)
    rows = [{"entity_type": "knowledge_chunk", "entity_id": chunk.id}]
    hidratados = UniversalSearchService()._hydrate_vector_candidates(  # noqa: SLF001
        db, rows, company=None, entity_types=None, collection_id=collection.id
    )
    assert len(hidratados) == 1
    candidato = hidratados[0]
    assert candidato.key == f"knowledge_chunk:{chunk.id}"
    assert candidato.title == "Documento bordes"
    assert candidato.text == "termino suelto"
    assert candidato.collection == "Coleccion bordes"
    assert candidato.collection_id == collection.id
    assert candidato.status == "active"
    assert candidato.metadata == {
        "knowledge_document_id": document.id,
        "page_number": 3,
        "source_locator": {},
    }


def test_hydrate_document_chunk_con_company(db_tenant) -> None:
    db, _tid = db_tenant
    company = _empresa(db)
    chunk = _documento_con_chunk(db, company)
    rows = [{"entity_type": "document_chunk", "entity_id": chunk.id}]
    hidratados = UniversalSearchService()._hydrate_vector_candidates(  # noqa: SLF001
        db, rows, company=company, entity_types=None, collection_id=None
    )
    assert len(hidratados) == 1
    candidato = hidratados[0]
    assert candidato.key == f"document_chunk:{chunk.id}"
    assert candidato.text == "termino repetido termino"
    assert candidato.ticker == "AAA"
    assert candidato.metadata["chunk_index"] == 0


# ------------------------------------------------- dedup y filtros del path vector


def test_search_vector_dedup_filtros_y_huerfanas(db_tenant, monkeypatch: pytest.MonkeyPatch) -> None:
    db, _tid = db_tenant
    company = _empresa(db)
    chunk = _documento_con_chunk(db, company)
    knowledge_chunk, _document, _collection = _knowledge_con_chunk(db, status="active")
    db.add(
        DecisionJournalEntry(
            company_id=company.id,
            decision="buy",
            rationale="termino de conviccion",
            what_must_be_true=["que siga el termino"],
        )
    )
    db.flush()

    class _RagFalsa:
        def search(self, query, *, ticker=None, limit=30, tenant_id=None):
            return [
                # Duplicada del candidato lexico: se omite (known_keys).
                {"entity_type": "document_chunk", "entity_id": chunk.id, "score": 0.9},
                # Hidratable pero filtrada por source_types (personal_note no pedido).
                {"entity_type": "knowledge_chunk", "entity_id": knowledge_chunk.id, "score": 0.8},
                # Huerfana: no hidrata, su clave no llega a by_key.
                {"entity_type": "document_chunk", "entity_id": 999999, "score": 0.7},
                # Tipo no hidratable: descartada en el bucle de hidratacion.
                {"entity_type": "investment_case", "entity_id": 5, "score": 0.6},
            ]

    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_SEARCH", "1")
    monkeypatch.setattr("app.services.rag.RAGIndex", _RagFalsa)

    resultado = UniversalSearchService().search(db, "termino", source_types={"annual_report"})
    citas = [item["citation"] for item in resultado["results"]]
    assert f"document_chunk:{chunk.id}" in citas
    assert f"knowledge_chunk:{knowledge_chunk.id}" not in citas
    assert "document_chunk:999999" not in citas
    assert resultado["retrieval"]["vector_status"] == "available"
