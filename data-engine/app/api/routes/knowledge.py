import logging
from datetime import date
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, ValidationError
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.errors import safe_detail
from app.core.tenancy import tenant_filters
from app.models import (
    InvestmentPrinciple,
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeDocument,
    ProcessingJob,
)
from app.schemas import ChatPageContext
from app.services.brain_service import resolve_page_context
from app.services.document_ingestion_service import MAX_DOCUMENT_BYTES
from app.services.knowledge_library_service import (
    KNOWLEDGE_DOCUMENT_TYPES,
    KnowledgeCollectionExistsError,
    KnowledgeLibraryService,
    normalize_knowledge_ticker,
)

router = APIRouter()

_logger = logging.getLogger(__name__)

KnowledgeLanguage = Literal["en", "es"]

_source_url_adapter: TypeAdapter[HttpUrl] = TypeAdapter(HttpUrl)


def _ref_error(status_code: int, message: str, exc: Exception) -> HTTPException:
    """Error genérico con referencia logueada (sin filtrar internos)."""
    ref = uuid4().hex[:8]
    _logger.exception("%s (ref=%s)", message, ref)
    return HTTPException(status_code=status_code, detail=f"{message} (ref {ref})")


def validate_upload_metadata(
    *, document_type: str, language: str, source_url: str | None
) -> tuple[str, str, str | None]:
    """Whitelist de ingesta: tipo cerrado, idioma cerrado, URL válida.

    Lanza ``ValueError`` con mensaje fijo (apto para 400) en cualquier
    rechazo; nunca incluye el valor ofensivo completo.
    """
    if document_type not in KNOWLEDGE_DOCUMENT_TYPES:
        raise ValueError("Unsupported knowledge document type")
    normalized_language = (language or "").strip().lower()
    if normalized_language not in ("en", "es"):
        raise ValueError("Unsupported knowledge language")
    validated_url: str | None = None
    if source_url:
        try:
            validated_url = str(_source_url_adapter.validate_python(source_url.strip()))
        except ValidationError as exc:
            raise ValueError("Invalid knowledge source_url") from exc
        # La cota se mide sobre la URL FINAL: la normalizacion ALARGA
        # ('/' final, IDN -> punycode) y HttpUrl solo corta en 2083, asi que
        # una entrada de <=1000 chars puede guardar >1000 y romper el INSERT
        # de KnowledgeDocument.source_url (String(1000)) en Postgres.
        if len(validated_url) > 1000:
            raise ValueError("Invalid knowledge source_url")
    return document_type, normalized_language, validated_url


class LibraryQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=1200)
    scope: Literal["letters", "library"] = "letters"
    author: str | None = Field(default=None, max_length=240)
    document_id: int | None = Field(default=None, ge=1)
    collection_id: int | None = Field(default=None, ge=1)
    mode: Literal["respuesta", "analisis"] = "respuesta"
    page: ChatPageContext | None = None


@router.post("/chat")
async def chat_library(payload: LibraryQuestion, db: Session = Depends(get_db)) -> dict:
    # La recuperación SQL/vector va en un hilo. La sesión solo se usa allí hasta terminar.
    from app.services.async_bridge import run_from_any_context
    from app.services.knowledge_chat import ask_library

    fields = payload.model_dump()
    page_context = resolve_page_context(db, payload.page)
    fields.pop("page", None)
    result = await run_in_threadpool(
        lambda: run_from_any_context(ask_library(db, **fields))
    )
    # Eco del contexto de página resuelto en servidor (pastilla "Viendo X").
    result["context"] = page_context.echo() if page_context else None
    return result


class CollectionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=240)
    description: str = Field(default="", max_length=4000)
    collection_type: str = Field(default="custom", min_length=2, max_length=80)


class PrincipleAction(BaseModel):
    action: str = Field(pattern="^(approve|reject|merge)$")
    actor: str = Field(default="user", min_length=1, max_length=160)
    canonical_principle_id: int | None = Field(default=None, ge=1)


class PrincipleRevision(BaseModel):
    principle: str | None = Field(default=None, min_length=3)
    category: str | None = Field(default=None, min_length=1, max_length=120)
    application_conditions: list[str] | None = None
    exceptions: list[str] | None = None
    applies_to_company_ids: list[int] | None = None
    exact_fragment: str | None = Field(default=None, min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    author: str | None = Field(default=None, max_length=240)
    confidence: float | None = Field(default=None, ge=0, le=1)
    actor: str = Field(default="user", min_length=1, max_length=160)


def _collection(collection: KnowledgeCollection) -> dict:
    return {
        "id": collection.id,
        "name": collection.name,
        "slug": collection.slug,
        "description": collection.description,
        "collection_type": collection.collection_type,
        "metadata": collection.metadata_,
    }


def _principle(principle: InvestmentPrinciple) -> dict:
    return {
        "id": principle.id,
        "knowledge_document_id": principle.knowledge_document_id,
        "knowledge_chunk_id": principle.knowledge_chunk_id,
        "collection_id": principle.collection_id,
        "principle": principle.principle,
        "principle_fingerprint": principle.principle_fingerprint,
        "semantic_duplicate_of_id": principle.semantic_duplicate_of_id,
        "canonical_principle_id": principle.canonical_principle_id,
        "version": principle.version,
        "superseded_by_id": principle.superseded_by_id,
        "category": principle.category,
        "application_conditions": principle.application_conditions,
        "exceptions": principle.exceptions,
        "applies_to_company_ids": principle.applies_to_company_ids,
        "exact_fragment": principle.exact_fragment,
        "page_number": principle.page_number,
        "author": principle.author,
        "confidence": principle.confidence,
        "status": principle.status,
        "approved_by": principle.approved_by,
        "approved_at": principle.approved_at,
        "metadata": principle.metadata_,
    }


def _job(job: ProcessingJob) -> dict:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "entity_type": job.entity_type,
        "entity_id": job.entity_id,
        "status": job.status,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "result": job.result,
        "error": job.error,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.post("/corpus/ingest-async", status_code=202)
def ingest_corpus_async(db: Session = Depends(get_db)) -> dict:
    """Encola la primera descarga del corpus libre de cartas para este tenant.

    Responde de inmediato (202): el actor `ingest_letters_corpus` descarga e
    ingiere los PDFs publicos (Numantia, Buffett, Azvalor, Magallanes) con el
    contexto de tenant del solicitante. Idempotente por dedupe SHA-256.
    """
    from app.workers.dramatiq_app import ingest_letters_corpus

    message = ingest_letters_corpus.send(
        tenant_id=db.info.get("tenant_id"),
        user_id=db.info.get("user_id"),
    )
    return {"status": "queued", "broker_message_id": str(message.message_id)}


@router.post("/collections/defaults")
def install_default_collections(db: Session = Depends(get_db)) -> list[dict]:
    return [
        _collection(collection)
        for collection in KnowledgeLibraryService().ensure_default_collections(db)
    ]


@router.get("/collections")
def list_collections(db: Session = Depends(get_db)) -> list[dict]:
    return [
        _collection(collection)
        for collection in db.scalars(
            select(KnowledgeCollection).order_by(KnowledgeCollection.name)
        ).all()
    ]


@router.post("/collections")
def create_collection(payload: CollectionCreate, db: Session = Depends(get_db)) -> dict:
    try:
        return _collection(
            KnowledgeLibraryService().create_collection(
                db,
                name=payload.name,
                description=payload.description,
                collection_type=payload.collection_type,
            )
        )
    except KnowledgeCollectionExistsError as exc:
        # 409 fijo: el nombre ya existe. Sin filtrar internos.
        raise HTTPException(
            status_code=409, detail="Knowledge collection already exists"
        ) from exc
    except ValueError as exc:
        # «!!» o «日本株» no dan slug: antes salia el 409 «ya existe» sin existir.
        raise HTTPException(
            status_code=422, detail="Collection name must contain letters or numbers"
        ) from exc


async def _read_upload_limited(file: UploadFile) -> bytes:
    content = bytearray()
    while chunk := await file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > MAX_DOCUMENT_BYTES:
            raise ValueError("Document exceeds 15MB local ingestion limit")
    return bytes(content)


@router.get("/documents")
def list_documents(
    collection_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    document_type: str | None = None,
    status: str | None = None,
    ticker: Annotated[str | None, Query(max_length=32)] = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    return KnowledgeLibraryService.list_documents(
        db, collection_id=collection_id, limit=limit, offset=offset,
        document_type=document_type, status=status, ticker=ticker,
    )


class DocumentTickerUpdate(BaseModel):
    """Ticker de la empresa a la que se refiere el documento; ``null`` lo quita."""

    ticker: str | None = Field(default=None, max_length=32)


@router.patch("/documents/{document_id}")
def update_document_ticker(
    document_id: int, payload: DocumentTickerUpdate, db: Session = Depends(get_db)
) -> dict:
    # db.get va con el filtro de tenant: otro tenant ve 404, como inexistente.
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    try:
        return KnowledgeLibraryService.set_document_ticker(db, document, payload.ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/documents/page")
def documents_page(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> dict:
    # Aggregates require explicit tenant predicates, unlike ORM entity loads.
    total = db.scalar(select(func.count()).select_from(KnowledgeDocument)
                      .where(*tenant_filters(db, KnowledgeDocument))) or 0
    counts = db.execute(
        select(KnowledgeDocument.collection_id, func.count())
        .where(*tenant_filters(db, KnowledgeDocument))
        .group_by(KnowledgeDocument.collection_id)
    ).all()
    return {
        "items": KnowledgeLibraryService.list_documents(db, limit=limit, offset=offset),
        "total": total,
        "collection_counts": {str(key): count for key, count in counts if key is not None},
    }


@router.get("/documents/search")
def search_documents(
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> dict:
    """Búsqueda de la Biblioteca por título, autor o ticker (sólo del tenant)."""
    return KnowledgeLibraryService.search_documents(db, q, limit=limit, offset=offset)


@router.get("/documents/{document_id}")
def get_document(document_id: int, db: Session = Depends(get_db)) -> dict:
    document = KnowledgeLibraryService.get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return document


@router.post("/documents/upload")
async def upload_document(
    title: str = Form(..., min_length=2, max_length=500),
    document_type: str = Form(...),
    collection_id: int | None = Form(default=None),
    author: str | None = Form(default=None, max_length=240),
    source_url: str | None = Form(default=None),
    publication_date: date | None = Form(default=None),
    language: str = Form(default="en", max_length=20),
    ticker: str | None = Form(default=None, max_length=32),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    try:
        validated_type, validated_language, validated_url = validate_upload_metadata(
            document_type=document_type, language=language, source_url=source_url
        )
        validated_ticker = normalize_knowledge_ticker(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        content = await _read_upload_limited(file)
        # La ingesta es sync y hace llamadas LLM (segundos): en un hilo del
        # pool para no bloquear el event loop mientras tanto.
        return await run_in_threadpool(
            KnowledgeLibraryService().ingest_bytes,
            db,
            title=title,
            document_type=validated_type,
            collection_id=collection_id,
            author=author,
            source_url=validated_url,
            publication_date=publication_date,
            language=validated_language,
            ticker=validated_ticker,
            content=content,
            filename=file.filename or "knowledge-document.bin",
            content_type=file.content_type,
        )
    except ValueError as exc:
        raise _ref_error(400, "Knowledge upload rejected", exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Knowledge ingestion failed") from exc


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int, db: Session = Depends(get_db)) -> Response:
    # db.get va con el filtro de tenant de la sesion: un documento de otro
    # tenant es None aqui y responde 404, igual que uno inexistente.
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    KnowledgeLibraryService.delete_document(db, document)
    return Response(status_code=204)


@router.delete("/collections/{collection_id}", status_code=204)
def delete_collection(collection_id: int, db: Session = Depends(get_db)) -> Response:
    # Mismo aislamiento que delete_document: db.get va con el filtro de
    # tenant de la sesion; una coleccion de otro tenant responde 404.
    collection = db.get(KnowledgeCollection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Knowledge collection not found")
    documents = db.scalar(
        select(func.count())
        .select_from(KnowledgeDocument)
        .where(
            KnowledgeDocument.collection_id == collection.id,
            *tenant_filters(db, KnowledgeDocument),
        )
    )
    if documents:
        # 409 fijo: solo se borran colecciones vacias. Con documentos hay
        # que borrar antes cada documento desde la propia biblioteca.
        raise HTTPException(status_code=409, detail="Knowledge collection is not empty")
    KnowledgeLibraryService.delete_collection(db, collection)
    return Response(status_code=204)


@router.get("/documents/{document_id}/chunks")
def document_chunks(
    document_id: int,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    if db.get(KnowledgeDocument, document_id) is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return [
        {
            "id": chunk.id,
            "knowledge_document_id": chunk.knowledge_document_id,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "page_number": chunk.page_number,
            "section_title": chunk.section_title,
            "token_count": chunk.token_count,
            "source_locator": chunk.source_locator,
            "metadata": chunk.metadata_,
        }
        for chunk in db.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.knowledge_document_id == document_id)
            .order_by(KnowledgeChunk.chunk_index)
            .offset(offset)
            .limit(limit)
        ).all()
    ]


@router.post("/documents/{document_id}/extract-principles")
def extract_principles(
    document_id: int,
    db: Session = Depends(get_db),
) -> dict:
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    active = db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.job_type == "knowledge_principle_extraction",
            ProcessingJob.entity_type == "knowledge_document",
            ProcessingJob.entity_id == document_id,
            ProcessingJob.status.in_(["queued", "running"]),
        )
        .order_by(desc(ProcessingJob.created_at))
    )
    if active:
        return _job(active)
    job = ProcessingJob(
        job_type="knowledge_principle_extraction",
        entity_type="knowledge_document",
        entity_id=document.id,
        status="queued",
        result={},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        from app.workers.dramatiq_app import extract_knowledge_principles

        message = extract_knowledge_principles.send(
            job.id,
            tenant_id=db.info.get("tenant_id"),
            user_id=db.info.get("user_id"),
        )
        job.result = {"broker_message_id": str(message.message_id)}
        db.commit()
        db.refresh(job)
        return _job(job)
    except Exception as exc:
        job.status = "failed"
        # El texto del broker (host, puerto, credenciales de la URL de Redis)
        # se queda en el log; job.error se persiste y lo devuelve tal cual
        # GET /api/knowledge/jobs/{id}.
        safe_detail(exc, 503)
        job.error = f"Queue dispatch failed: {type(exc).__name__}"
        db.commit()
        raise HTTPException(
            status_code=503,
            detail={"message": "Principle extraction queue is unavailable", "job_id": job.id},
        ) from exc


@router.get("/jobs")
def list_jobs(
    document_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = select(ProcessingJob).where(
        ProcessingJob.job_type == "knowledge_principle_extraction"
    )
    if document_id is not None:
        statement = statement.where(ProcessingJob.entity_id == document_id)
    return [
        _job(job)
        for job in db.scalars(
            statement.order_by(desc(ProcessingJob.created_at), desc(ProcessingJob.id)).limit(limit)
        ).all()
    ]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    job = db.get(ProcessingJob, job_id)
    if job is None or job.job_type != "knowledge_principle_extraction":
        raise HTTPException(status_code=404, detail="Processing job not found")
    return _job(job)


@router.get("/principles/page")
def principles_page(
    status: str | None = Query(default=None),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> dict:
    statement = select(InvestmentPrinciple)
    count = select(func.count()).select_from(InvestmentPrinciple).where(
        *tenant_filters(db, InvestmentPrinciple)
    )
    if status:
        statement = statement.where(InvestmentPrinciple.status == status)
        count = count.where(InvestmentPrinciple.status == status)
    return {
        "items": [_principle(item) for item in db.scalars(
            statement.order_by(desc(InvestmentPrinciple.created_at), desc(InvestmentPrinciple.id))
            .limit(limit).offset(offset)
        ).all()],
        "total": db.scalar(count) or 0,
        "proposed_total": db.scalar(select(func.count()).select_from(InvestmentPrinciple)
                                    .where(InvestmentPrinciple.status == "proposed",
                                           *tenant_filters(db, InvestmentPrinciple))) or 0,
    }


@router.get("/principles")
def list_principles(
    status: str | None = Query(default=None),
    collection_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = select(InvestmentPrinciple)
    if status:
        statement = statement.where(InvestmentPrinciple.status == status)
    if collection_id is not None:
        statement = statement.where(InvestmentPrinciple.collection_id == collection_id)
    return [
        _principle(principle)
        for principle in db.scalars(
            statement.order_by(desc(InvestmentPrinciple.created_at)).limit(limit)
        ).all()
    ]


@router.post("/principles/{principle_id}/action")
def action_principle(
    principle_id: int,
    payload: PrincipleAction,
    db: Session = Depends(get_db),
) -> dict:
    principle = db.get(InvestmentPrinciple, principle_id)
    if principle is None:
        raise HTTPException(status_code=404, detail="Investment principle not found")
    try:
        if payload.action == "merge":
            canonical = db.get(InvestmentPrinciple, payload.canonical_principle_id)
            if canonical is None:
                raise ValueError("Canonical principle was not found")
            return _principle(
                KnowledgeLibraryService().merge_principle(
                    db,
                    principle,
                    canonical=canonical,
                    actor=payload.actor,
                )
            )
        return _principle(
            KnowledgeLibraryService().decide_principle(
                db,
                principle,
                action=payload.action,
                actor=payload.actor,
            )
        )
    except ValueError as exc:
        raise _ref_error(409, "Principle action conflict", exc) from exc


@router.put("/principles/{principle_id}")
def revise_principle(
    principle_id: int,
    payload: PrincipleRevision,
    db: Session = Depends(get_db),
) -> dict:
    principle = db.get(InvestmentPrinciple, principle_id)
    if principle is None:
        raise HTTPException(status_code=404, detail="Investment principle not found")
    changes = payload.model_dump(exclude={"actor"}, exclude_none=True)
    if not changes:
        raise HTTPException(status_code=400, detail="At least one revision field is required")
    try:
        return _principle(
            KnowledgeLibraryService().revise_principle(
                db,
                principle,
                changes=changes,
                actor=payload.actor,
            )
        )
    except ValueError as exc:
        raise _ref_error(409, "Principle revision conflict", exc) from exc
