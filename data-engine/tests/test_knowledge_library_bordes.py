"""Bordes de app.services.knowledge_library_service (lote KL1).

SQLite real en memoria con un Tenant y db.info["tenant_id"] (patron de
tests/test_knowledge_library.py). El LLM siempre va doblado con una subclase de
LLMProvider de payloads literales: no hay llamadas reales. BudgetController,
DocumentStore y RAGIndex se doblan en los tests que los necesitan (clases
definidas dentro del test: su estado muere con el). parser de .txt real en
memoria; sin red, sin qdrant, sin disco fuera de pytest.
"""

import asyncio
import json
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.knowledge_library_service as kls
from app.core.database import Base
from app.llm import LLMRequest, LLMResponse, Message, TaskModelRouter, Usage
from app.llm.base import LLMProvider
from app.models import (
    InvestmentPrinciple,
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeDocument,
    Tenant,
)
from app.services.knowledge_library_service import (
    DEFAULT_KNOWLEDGE_COLLECTIONS,
    KnowledgeCollectionExistsError,
    KnowledgeLibraryService,
)


@pytest.fixture
def db_tenant():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id="kl-bordes", name="KL bordes")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id
        yield db, tenant.id


class _Provider(LLMProvider):
    """LLM falso: devuelve siempre el payload literal con el que se construye."""

    name = "test-bordes"

    def __init__(self, payload: dict) -> None:
        super().__init__(
            model_router=TaskModelRouter(default_model="test-model"),
            timeout_seconds=1,
            max_retries=0,
        )
        self._payload = payload
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            message=Message("assistant", json.dumps(self._payload)),
            usage=Usage(input_tokens=10, output_tokens=10, total_tokens=20),
            model="test-model",
            provider=self.name,
        )


def _documento(db: Session, tenant_id: int, **kwargs) -> KnowledgeDocument:
    kwargs.setdefault("title", "Documento de bordes")
    kwargs.setdefault("document_type", "personal_note")
    documento = KnowledgeDocument(tenant_id=tenant_id, **kwargs)
    db.add(documento)
    db.flush()
    return documento


def _chunk(
    db: Session, documento: KnowledgeDocument, tenant_id: int, content: str, index: int = 0
) -> KnowledgeChunk:
    chunk = KnowledgeChunk(
        knowledge_document_id=documento.id,
        chunk_index=index,
        content=content,
        token_count=len(content.split()),
        tenant_id=tenant_id,
    )
    db.add(chunk)
    db.flush()
    return chunk


CONTENIDO = (
    "The best businesses can reinvest incremental capital at high rates of return in their operations."
)
FRAGMENTO = "reinvest incremental capital"


def _payload_valido(chunk_id: int, principio: str = "Reinvestment creates durable value") -> dict:
    return {
        "principles": [
            {
                "principle": principio,
                "category": "general",
                "application_conditions": ["high incremental returns"],
                "exceptions": [],
                "company_tickers": [],
                "exact_fragment": FRAGMENTO,
                "chunk_id": chunk_id,
                "confidence": 0.91,
            }
        ]
    }


# ----------------------------------------------------------------------- colecciones


def test_ensure_default_collections_idempotente(db_tenant) -> None:
    db, _tid = db_tenant
    servicio = KnowledgeLibraryService()
    primera = servicio.ensure_default_collections(db)
    segunda = servicio.ensure_default_collections(db)
    assert len(primera) == len(segunda) == len(DEFAULT_KNOWLEDGE_COLLECTIONS)
    assert {c.name for c in segunda} == set(DEFAULT_KNOWLEDGE_COLLECTIONS)
    assert len({c.slug for c in segunda}) == len(segunda)  # la segunda pasada no duplica


def test_create_collection_duplicada(db_tenant) -> None:
    db, _tid = db_tenant
    servicio = KnowledgeLibraryService()
    servicio.ensure_default_collections(db)
    with pytest.raises(KnowledgeCollectionExistsError) as excinfo:
        servicio.create_collection(db, name="Buffett & Munger")
    assert str(excinfo.value) == "Knowledge collection 'Buffett & Munger' already exists"


# ----------------------------------------------------------------------- ingest_bytes


def test_ingest_vacio(db_tenant) -> None:
    db, _tid = db_tenant
    with pytest.raises(ValueError) as excinfo:
        KnowledgeLibraryService().ingest_bytes(
            db, title="t", content=b"", filename="a.txt", document_type="personal_note"
        )
    assert str(excinfo.value) == "Knowledge document is empty"


def test_ingest_demasiado_grande(db_tenant) -> None:
    db, _tid = db_tenant
    with pytest.raises(ValueError) as excinfo:
        KnowledgeLibraryService().ingest_bytes(
            db,
            title="t",
            content=b"x" * (15 * 1024 * 1024 + 1),
            filename="a.txt",
            document_type="personal_note",
        )
    assert str(excinfo.value) == "Knowledge document exceeds 15MB local ingestion limit"


def test_ingest_tipo_no_soportado(db_tenant) -> None:
    db, _tid = db_tenant
    with pytest.raises(ValueError) as excinfo:
        KnowledgeLibraryService().ingest_bytes(
            db, title="t", content=b"contenido", filename="a.txt", document_type="wodget"
        )
    assert str(excinfo.value) == "Unsupported knowledge document type: wodget"


def test_ingest_coleccion_inexistente(db_tenant) -> None:
    db, _tid = db_tenant
    with pytest.raises(ValueError) as excinfo:
        KnowledgeLibraryService().ingest_bytes(
            db,
            title="t",
            content=b"contenido",
            filename="a.txt",
            document_type="personal_note",
            collection_id=999999,
        )
    assert str(excinfo.value) == "Knowledge collection not found"


def test_ingest_extension_no_soportada(db_tenant) -> None:
    db, _tid = db_tenant
    with pytest.raises(ValueError) as excinfo:
        KnowledgeLibraryService().ingest_bytes(
            db,
            title="t",
            content=b"contenido valido con mas de veinte caracteres",
            filename="x.exe",
            document_type="personal_note",
        )
    assert str(excinfo.value) == "Unsupported document extension: .exe"


def test_ingest_parser_con_muy_poco_texto(db_tenant) -> None:
    db, _tid = db_tenant
    with pytest.raises(ValueError) as excinfo:
        KnowledgeLibraryService().ingest_bytes(
            db, title="t", content=b"poco", filename="a.txt", document_type="personal_note"
        )
    assert str(excinfo.value) == "Knowledge document parser produced too little text"


def test_ingest_con_indice_vectorial_activado(db_tenant, monkeypatch: pytest.MonkeyPatch) -> None:
    db, tid = db_tenant

    class _StoreFalso:
        def __init__(self) -> None:
            self.llamadas: list[tuple] = []

        def put_bytes(
            self,
            categoria: str,
            tipo: str,
            nombre: str,
            contenido: bytes,
            tenant_id=None,
            content_type: str | None = None,
        ) -> str:
            self.llamadas.append((categoria, tipo, nombre, contenido, tenant_id, content_type))
            return "local://fake-uri"

    class _RagFalso:
        def ingest_knowledge_document(self, db: Session, document: KnowledgeDocument) -> dict:
            return {"chunks_indexed": 3}

    almacen = _StoreFalso()
    monkeypatch.setattr(kls, "DocumentStore", lambda: almacen)
    monkeypatch.setattr("app.services.rag.RAGIndex", _RagFalso)
    monkeypatch.setenv("CAVAAI_ENABLE_VECTOR_INGEST", "1")

    resultado = KnowledgeLibraryService().ingest_bytes(
        db,
        title="Nota vectorial",
        content=CONTENIDO.encode(),
        filename="nota.txt",
        document_type="personal_note",
    )
    assert resultado["status"] == "ingested"
    assert resultado["chunks"] == 1
    assert resultado["storage_uri"] == "local://fake-uri"
    assert resultado["vector_index"] == {"status": "attempted", "chunks_indexed": 3}
    assert len(almacen.llamadas) == 1
    assert almacen.llamadas[0][0] == "KNOWLEDGE"
    assert almacen.llamadas[0][4] == tid
    assert almacen.llamadas[0][5] == "application/octet-stream"


# ------------------------------------------------------------------ extract_principles


def test_extract_sin_chunks(db_tenant) -> None:
    db, tid = db_tenant
    documento = _documento(db, tid)
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(KnowledgeLibraryService().extract_principle_batches(db, documento))
    assert str(excinfo.value) == "Knowledge document has no chunks"


def test_extract_corte_por_presupuesto_sin_llamar_al_llm(db_tenant, monkeypatch: pytest.MonkeyPatch) -> None:
    db, tid = db_tenant
    documento = _documento(db, tid)
    _chunk(db, documento, tid, CONTENIDO)
    provider = _Provider(_payload_valido(0))

    class _BudgetFalso:
        def estimate_cost_eur(self, nombre: str, *, input_tokens: int, output_tokens: int) -> Decimal:
            return Decimal("0.01")

        def can_spend(self, db: Session, cantidad: Decimal) -> bool:
            return False

    monkeypatch.setattr(kls, "BudgetController", _BudgetFalso)
    resultado = asyncio.run(KnowledgeLibraryService(provider).extract_principle_batches(db, documento))
    assert resultado["budget_stopped"] is True
    assert resultado["batches_processed"] == 0
    assert resultado["batch_count"] == 1
    assert resultado["principles"] == []
    assert provider.requests == []  # el gate de presupuesto va antes que el LLM


def test_extract_respuesta_sin_lista_de_principios(db_tenant) -> None:
    db, tid = db_tenant
    documento = _documento(db, tid)
    chunk = _chunk(db, documento, tid, CONTENIDO)
    provider = _Provider({"principles": "no-es-una-lista"})
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(KnowledgeLibraryService(provider).extract_principle_batches(db, documento))
    assert str(excinfo.value) == "Invalid investment principle extraction response"
    assert provider.requests != []  # si llamo al LLM; la respuesta era invalida
    _ = chunk


def test_extract_principio_con_chunk_inexistente_se_descarta(db_tenant) -> None:
    db, tid = db_tenant
    documento = _documento(db, tid)
    _chunk(db, documento, tid, CONTENIDO)
    provider = _Provider(_payload_valido(999999))
    resultado = asyncio.run(KnowledgeLibraryService(provider).extract_principle_batches(db, documento))
    assert resultado["principles"] == []
    assert resultado["batches_processed"] == 1
    assert resultado["exact_duplicates"] == 0
    assert resultado["semantic_duplicates"] == 0


def test_extract_duplicado_semantico_lo_cuenta(db_tenant) -> None:
    db, tid = db_tenant
    documento = _documento(db, tid)
    chunk = _chunk(db, documento, tid, CONTENIDO)
    semilla = InvestmentPrinciple(
        knowledge_document_id=documento.id,
        principle="reinvestment creates durable value",
        principle_fingerprint="huella-semilla-distinta",
        category="capital_allocation",
        exact_fragment="x",
        status="proposed",
        tenant_id=tid,
    )
    db.add(semilla)
    db.flush()
    provider = _Provider(_payload_valido(chunk.id))
    resultado = asyncio.run(KnowledgeLibraryService(provider).extract_principle_batches(db, documento))
    assert resultado["semantic_duplicates"] == 1
    assert len(resultado["principles"]) == 1
    creado = resultado["principles"][0]
    assert creado.semantic_duplicate_of_id == semilla.id
    assert creado.canonical_principle_id == semilla.id
    assert creado.metadata_["requires_duplicate_review"] is True


def test_extract_llama_a_progress(db_tenant) -> None:
    db, tid = db_tenant
    documento = _documento(db, tid)
    chunk = _chunk(db, documento, tid, CONTENIDO)
    llamadas: list[tuple[int, int]] = []
    resultado = asyncio.run(
        KnowledgeLibraryService(_Provider(_payload_valido(chunk.id))).extract_principle_batches(
            db, documento, progress=lambda hecho, total: llamadas.append((hecho, total))
        )
    )
    assert resultado["batches_processed"] == 1
    assert len(resultado["principles"]) == 1
    assert llamadas == [(1, 1)]


def test_merge_solo_propuestos(db_tenant) -> None:
    db, tid = db_tenant
    documento = _documento(db, tid)
    principio = InvestmentPrinciple(
        knowledge_document_id=documento.id,
        principle="ya aprobado",
        principle_fingerprint="huella-aprobada",
        category="general",
        exact_fragment="x",
        status="approved",
        tenant_id=tid,
    )
    db.add(principio)
    db.flush()
    with pytest.raises(ValueError) as excinfo:
        KnowledgeLibraryService().merge_principle(db, principio, canonical=principio, actor="nico")
    assert str(excinfo.value) == "Only proposed principles can be merged"


# --------------------------------------------------------------- _create_principle_candidate


def test_candidato_item_no_diccionario(db_tenant) -> None:
    db, tid = db_tenant
    documento = _documento(db, tid)
    assert (
        KnowledgeLibraryService()._create_principle_candidate(
            db,
            document=documento,
            chunks_by_id={},
            companies={},
            item="no-es-un-dict",
            response=None,
            batch_index=0,
            batch_count=1,
        )
        is None
    )


@pytest.mark.parametrize(
    "item",
    [
        {"chunk_id": 123, "principle": "p", "exact_fragment": "f"},  # chunk inexistente
        {"chunk_id": 0, "exact_fragment": "f"},  # sin texto de principio
        {"chunk_id": 0, "principle": "p"},  # sin fragmento exacto
        {"chunk_id": 0, "principle": "p", "exact_fragment": "no esta en el contenido"},
    ],
    ids=["chunk-inexistente", "sin-principio", "sin-fragmento", "fragmento-ajeno"],
)
def test_candidato_invalido_devuelve_none(db_tenant, item: dict) -> None:
    db, tid = db_tenant
    documento = _documento(db, tid)
    chunk = _chunk(db, documento, tid, CONTENIDO)
    if item.get("chunk_id") == 0:
        item = {**item, "chunk_id": chunk.id}
    assert (
        KnowledgeLibraryService()._create_principle_candidate(
            db,
            document=documento,
            chunks_by_id={chunk.id: chunk},
            companies={},
            item=item,
            response=None,
            batch_index=0,
            batch_count=1,
        )
        is None
    )


def test_principle_batches_vacio() -> None:
    assert KnowledgeLibraryService._principle_batches([]) == []


# ------------------------------------------------------------------ listado y busqueda


def test_list_documents_filtra_por_coleccion(db_tenant) -> None:
    db, tid = db_tenant
    coleccion = KnowledgeCollection(
        name="Coleccion A", slug="coleccion-a", description="", collection_type="custom", tenant_id=tid
    )
    db.add(coleccion)
    db.flush()
    propio = _documento(db, tid, title="De la coleccion", collection_id=coleccion.id)
    _documento(db, tid, title="Sin coleccion")
    listado = KnowledgeLibraryService.list_documents(db, collection_id=coleccion.id)
    assert [d["id"] for d in listado] == [propio.id]


def test_search_documents_vacia(db_tenant) -> None:
    db, _tid = db_tenant
    assert KnowledgeLibraryService.search_documents(db, "   ") == {"items": [], "total": 0, "query": ""}


def test_search_documents_literal_y_tenant(db_tenant) -> None:
    db, tid = db_tenant
    otro = Tenant(external_id="kl-otro", name="Otro")
    db.add(otro)
    db.flush()
    propio = _documento(db, tid, title="Nota 100% real", ticker="SAN.MC", author="Autor Uno")
    db.info["tenant_id"] = otro.id
    _documento(db, otro.id, title="Nota 100% real de otro tenant", ticker="SAN.MC")
    db.info["tenant_id"] = tid
    porcentaje = KnowledgeLibraryService.search_documents(db, "100%")
    assert porcentaje["total"] == 1
    assert [d["id"] for d in porcentaje["items"]] == [propio.id]
    assert porcentaje["query"] == "100%"
    por_ticker = KnowledgeLibraryService.search_documents(db, "san.mc")
    assert [d["id"] for d in por_ticker["items"]] == [propio.id]
    assert KnowledgeLibraryService.search_documents(db, "100x")["total"] == 0


# ------------------------------------------------------------------------- varios


def test_delete_vector_points_sin_tenant_no_hace_nada(db_tenant) -> None:
    db, tid = db_tenant
    documento = _documento(db, tid)
    db.info.pop("tenant_id")  # sesion desechada al cerrar el test
    KnowledgeLibraryService._delete_vector_points(db, documento)


def test_delete_vector_points_traga_errores(db_tenant, monkeypatch: pytest.MonkeyPatch) -> None:
    db, tid = db_tenant
    documento = _documento(db, tid)

    class _RagRoto:
        def delete_knowledge_document_points(self, tenant_id: int, document_id: int) -> None:
            raise ConnectionError("qdrant caido")

    monkeypatch.setattr("app.services.rag.RAGIndex", _RagRoto)
    KnowledgeLibraryService._delete_vector_points(db, documento)  # no propaga


def test_strings() -> None:
    assert KnowledgeLibraryService._strings("no es una lista") == []
    assert KnowledgeLibraryService._strings([" a ", "", "b"]) == ["a", "b"]


def test_integer() -> None:
    assert KnowledgeLibraryService._integer("abc") is None
    assert KnowledgeLibraryService._integer(None) is None
    assert KnowledgeLibraryService._integer("7") == 7
