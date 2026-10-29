from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, union
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.errors import safe_detail
from app.core.tenancy import tenant_filters
from app.llm.errors import LLMError
from app.models import (
    Company,
    Document,
    DocumentChunk,
    KPIExtractionCandidate,
    Position,
    SourceAudit,
    ThesisVersion,
    WatchItem,
)
from app.schemas import (
    KPIExtractionAction,
    KPIExtractionCandidateOut,
)
from app.services.async_bridge import run_from_any_context
from app.services.budget import BudgetExceededError
from app.services.claim_intelligence_service import ClaimIntelligenceService
from app.services.company_resolver import resolve_companies, resolve_company
from app.services.document_ingestion_service import MAX_DOCUMENT_BYTES, DocumentIngestionService
from app.services.document_visibility import without_archive_duplicates
from app.services.kpi_extraction_service import KPIExtractionService
from app.services.manual_transcript_import_service import ManualTranscriptImportService
from app.services.rag import RAGIndex
from app.services.source_hierarchy_service import classify_source

router = APIRouter()


class ManualTranscriptImportRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=3, max_length=500)
    text: str = Field(min_length=20)
    source_url: str | None = None
    period: str = "unknown"


class UrlIngestRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=3, max_length=500)
    url: str = Field(min_length=8, max_length=2000)
    source_type: str = Field(default="url", min_length=2, max_length=80)


@router.post("/documents/index/rebuild")
def rebuild_document_index(db: Session = Depends(get_db)) -> dict:
    try:
        return RAGIndex().rebuild_tenant(db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=safe_detail(exc, 502)) from exc


def _followed_company_ids(db: Session):
    """Empresas del universo seguido del tenant: cartera + watchlist.

    `Company` es global (no tenant-owned); la pertenencia se decide por las
    filas `Position`/`WatchItem` del tenant. Un documento sin empresa no entra
    en `followed`: no se puede afirmar que sea de una empresa seguida.
    """
    held = select(Position.company_id).where(*tenant_filters(db, Position))
    # La watchlist guarda el simbolo tal cual lo escribio el usuario (SAN.MC,
    # BRK.B, minusculas...). Se resuelve con el mismo `resolve_company` que la
    # ficha para que un valor con sufijo de mercado cuente como seguido.
    symbols = set(db.scalars(select(WatchItem.symbol).where(*tenant_filters(db, WatchItem))).all())
    # Un solo lote (1-2 IN) en vez de una resolucion por simbolo: el coste no
    # crece con el tamano de la watchlist.
    resolved, _missing = resolve_companies(db, sorted(symbol for symbol in symbols if symbol))
    watched_ids = {company.id for company in resolved}
    watched = select(Company.id).where(Company.id.in_(watched_ids))
    return union(held, watched)


def _effective_scope(scope: str | None, ticker: str | None) -> str:
    """Scope por defecto: una consulta explicita por ticker NO se acota.

    Sin `scope`, un `ticker` pedido de forma explicita consulta esa empresa
    (como antes del filtro de universo seguido); sin ticker, el inventario
    global usa `followed`. Un `scope` explicito siempre se respeta.
    """
    if scope is not None:
        return scope
    return "all" if ticker else "followed"


def _document_filters(
    db: Session,
    *,
    company: Company | None,
    scope: str,
    source_type: str | None,
    q: str | None,
) -> list:
    """Filtros compartidos por listado y recuento: mismo subconjunto exacto."""
    filters = []
    tenant_id = db.info.get("tenant_id")
    if tenant_id is not None:
        filters.append(Document.tenant_id == tenant_id)
    if company is not None:
        filters.append(Document.company_id == company.id)
    if scope == "followed":
        filters.append(Document.company_id.in_(_followed_company_ids(db)))
    if source_type:
        filters.append(Document.source_type == source_type)
    search = (q or "").strip()
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(Document.title.ilike(f"%{escaped}%", escape="\\"))
    return filters


@router.get("/documents")
def documents(
    ticker: str | None = None,
    scope: Annotated[str | None, Query(pattern="^(followed|all)$")] = None,
    source_type: Annotated[str | None, Query(max_length=80)] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    include_chunks: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    chunk_limit: int = Query(default=1000, ge=1, le=1000),
    chunk_text_limit: int = Query(default=1500, ge=120, le=10000),
    db: Session = Depends(get_db),
) -> list[dict]:
    company = None
    if ticker:
        # F313: mismo criterio de identidad que /api/companies/{ticker}: el
        # alias europeo (SAN.MC -> SAN) resuelve a la empresa base; el match
        # literal dejaba la pestaña de documentos vacía para esos tickers.
        company = resolve_company(db, ticker)
        if company is None:
            return []
    statement = (
        select(Document, Company)
        .outerjoin(Company, Document.company_id == Company.id)
        .where(
            *_document_filters(
                db,
                company=company,
                scope=_effective_scope(scope, ticker),
                source_type=source_type,
                q=q,
            )
        )
    )
    statement = without_archive_duplicates(statement)

    # «Mas recientes» = por fecha de PUBLICACION global, no por ingesta:
    # ordenar por created_at agrupaba por tanda de ingesta y desplazaba
    # filings recientes de otros emisores fuera del limite (F162). Los sin
    # fecha de publicacion van al final (la UI los etiqueta «sin fecha»);
    # created_at solo desempata dentro de la misma fecha.
    rows = db.execute(
        statement.order_by(desc(Document.published_at).nullslast(), desc(Document.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    chunk_map: dict[int, list[dict]] = {}
    if include_chunks and rows:
        document_ids = [document.id for document, _ in rows]
        chunks = db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id.in_(document_ids))
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
            .limit(chunk_limit)
        ).all()
        for chunk in chunks:
            chunk_map.setdefault(chunk.document_id, []).append(
                {
                    "id": chunk.id,
                    "document_id": chunk.document_id,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text[:chunk_text_limit],
                    "token_count": chunk.token_count,
                    "metadata": chunk.metadata_,
                }
            )

    return [
        {
            "id": document.id,
            "ticker": company.ticker if company else None,
            "title": document.title,
            "source_type": document.source_type,
            "source_tier": classify_source(document.source_type, document.source_url).key,
            "source_url": document.source_url,
            "storage_uri": document.storage_uri,
            "checksum": document.checksum,
            "metadata": document.metadata_,
            "published_at": document.published_at.isoformat() if document.published_at else None,
            "chunks": chunk_map.get(document.id, []) if include_chunks else [],
        }
        for document, company in rows
    ]


@router.get("/documents/count")
def documents_count(
    ticker: str | None = None,
    scope: Annotated[str | None, Query(pattern="^(followed|all)$")] = None,
    source_type: Annotated[str | None, Query(max_length=80)] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    db: Session = Depends(get_db),
) -> dict:
    """Total real de documentos que cumplen los MISMOS filtros que /documents.

    La lista /documents pagina (50 por defecto): sin este total, la UI
    presentaba el tamano de pagina como si fuera el inventario completo
    y el resto de documentos quedaba inalcanzable (F131).
    """
    # with_loader_criteria no alcanza un SELECT de agregado: el tenant se
    # filtra explicito para no contar documentos de otros tenants.
    company = None
    if ticker:
        # F313: alias europeo resuelto con la misma política que la ficha.
        company = resolve_company(db, ticker)
        if company is None:
            return {"total": 0}
    statement = (
        select(func.count())
        .select_from(Document)
        .outerjoin(Company, Document.company_id == Company.id)
        .where(
            *_document_filters(
                db,
                company=company,
                scope=_effective_scope(scope, ticker),
                source_type=source_type,
                q=q,
            )
        )
    )
    statement = without_archive_duplicates(statement)
    return {"total": int(db.execute(statement).scalar_one())}


@router.get("/documents/{document_id}/chunks")
def document_chunks(
    document_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    text_limit: int = Query(default=1800, ge=120, le=10000),
    db: Session = Depends(get_db),
) -> list[dict]:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    chunks = list(
        db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.chunk_index)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return [
        {
            "id": chunk.id,
            "document_id": chunk.document_id,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text[:text_limit],
            "token_count": chunk.token_count,
            "metadata": chunk.metadata_,
        }
        for chunk in chunks
    ]


@router.post("/documents/{document_id}/analyze")
def analyze_document(document_id: int, db: Session = Depends(get_db)) -> dict:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return ClaimIntelligenceService().scan_document(db, document, auto_apply=True)


@router.post(
    "/documents/{document_id}/extract-kpis",
    response_model=list[KPIExtractionCandidateOut],
)
async def extract_document_kpis(
    document_id: int, db: Session = Depends(get_db)
) -> list[KPIExtractionCandidate]:
    document = await run_in_threadpool(db.get, Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        # La extraccion mezcla sqlalchemy y el LLM: hilo del pool, con la
        # corutina del servicio puenteado (no bloquea el event loop).
        return await run_in_threadpool(
            lambda: run_from_any_context(KPIExtractionService().extract_document(db, document))
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMError as exc:
        # El texto de LLMError es diagnostico interno (proveedor, estado HTTP,
        # motivo de configuracion), no un mensaje para el usuario.
        raise HTTPException(status_code=503, detail="El modelo no está disponible ahora; reintenta más tarde.") from exc
    except BudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@router.get("/kpi-candidates", response_model=list[KPIExtractionCandidateOut])
def kpi_candidates(
    ticker: str | None = None,
    document_id: int | None = None,
    status: str | None = "pending_approval",
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[KPIExtractionCandidate]:
    statement = select(KPIExtractionCandidate)
    if ticker:
        company = resolve_company(db, ticker)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        statement = statement.where(KPIExtractionCandidate.company_id == company.id)
    if document_id is not None:
        statement = statement.where(KPIExtractionCandidate.document_id == document_id)
    if status:
        statement = statement.where(KPIExtractionCandidate.status == status)
    return list(
        db.scalars(
            statement.order_by(
                desc(KPIExtractionCandidate.confidence),
                desc(KPIExtractionCandidate.created_at),
            ).limit(limit)
        ).all()
    )


@router.post(
    "/kpi-candidates/{candidate_id}/action",
    response_model=KPIExtractionCandidateOut,
)
def action_kpi_candidate(
    candidate_id: int,
    payload: KPIExtractionAction,
    db: Session = Depends(get_db),
) -> KPIExtractionCandidate:
    candidate = db.get(KPIExtractionCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="KPI candidate not found")
    try:
        service = KPIExtractionService()
        if payload.action == "approve":
            service.approve(db, candidate, actor=payload.actor)
        else:
            service.reject(db, candidate, actor=payload.actor)
        db.refresh(candidate)
        return candidate
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/documents/ingest-file")
async def ingest_document_file(
    ticker: str = Form(..., min_length=1, max_length=20),
    title: str = Form(..., min_length=3, max_length=500),
    source_type: str = Form(default="manual_upload", min_length=2, max_length=80),
    source_url: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    try:
        content = bytearray()
        while chunk := await file.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > MAX_DOCUMENT_BYTES:
                raise ValueError("Document exceeds 15MB local ingestion limit")
        # Ingesta sync con llamadas externas: en el pool de hilos para no
        # bloquear el event loop (esta ruta es async).
        return await run_in_threadpool(
            DocumentIngestionService().ingest_bytes,
            db,
            ticker=ticker,
            title=title,
            content=bytes(content),
            filename=file.filename or "upload.bin",
            source_type=source_type,
            source_url=source_url,
            content_type=file.content_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Document ingestion failed") from exc


@router.post("/documents/ingest-url")
def ingest_document_url(payload: UrlIngestRequest, db: Session = Depends(get_db)) -> dict:
    try:
        return DocumentIngestionService().ingest_url(
            db,
            ticker=payload.ticker,
            title=payload.title,
            url=payload.url,
            source_type=payload.source_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="URL ingestion failed") from exc


@router.get("/audits")
def source_audits(
    ticker: str | None = Query(default=None, min_length=1, max_length=20),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = (
        select(SourceAudit, ThesisVersion.version)
        .outerjoin(ThesisVersion, SourceAudit.thesis_version_id == ThesisVersion.id)
        .order_by(desc(SourceAudit.created_at))
    )
    if ticker:
        # F313: alias europeo (SAN.MC -> SAN) con la misma política que la
        # ficha; el literal dejaba las auditorías vacías para esos tickers.
        company = resolve_company(db, ticker)
        if company is None:
            return []
        statement = statement.where(ThesisVersion.company_id == company.id)
    statement = statement.offset(offset).limit(limit)
    return [
        {
            "id": audit.id,
            "thesis_version_id": audit.thesis_version_id,
            "thesis_version": version,
            "created_at": audit.created_at.isoformat() if audit.created_at else None,
            "passed": audit.passed,
            "source_coverage_score": audit.source_coverage_score,
            "unsupported_claims": audit.unsupported_claims,
            "weak_claims": audit.weak_claims,
            "data_conflicts": audit.data_conflicts,
            "required_fixes": audit.required_fixes,
        }
        for audit, version in db.execute(statement).all()
    ]


@router.post("/transcripts/import-text")
def import_transcript_text(
    payload: ManualTranscriptImportRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        return ManualTranscriptImportService().import_text(
            db=db,
            ticker=payload.ticker,
            title=payload.title,
            text=payload.text,
            source_url=payload.source_url,
            period=payload.period,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
