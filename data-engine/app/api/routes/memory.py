import re
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models import (
    Claim,
    ClaimEvidence,
    Company,
    Document,
    DocumentChunk,
    MemoryItem,
    ResearchSession,
    ThesisChange,
    ThesisSection,
    ThesisVersion,
)
from app.schemas import (
    ClaimCreate,
    ClaimEvidenceCreate,
    ClaimEvidenceOut,
    ClaimOut,
    MemoryItemCreate,
    MemoryItemOut,
    ResearchSessionCreate,
    ResearchSessionOut,
    ThesisChangeCreate,
    ThesisChangeOut,
    ThesisSectionCreate,
    ThesisSectionOut,
)
from app.services.company_resolver import resolve_company
from app.services.review_alert_service import ReviewAlertService
from app.services.review_copy import claim_status_label
from app.services.source_hierarchy_service import classify_source
from app.services.thesis_change_types import claim_change_type
from app.services.ticker_news_lane import is_law_firm_solicitation

router = APIRouter()

# Enums cerrados de memory-items (los schemas transportan str libre; la ruta
# es la que cierra el contrato con 400 fijo en vez de persistir basura).
MemoryScope = Literal["portfolio", "company"]
MemoryType = Literal["note", "chat_memory", "watch_item", "embedding"]
MemoryStatus = Literal["active", "archived", "consolidated"]
MemorySourceType = Literal["user", "chat"]
ResearchSessionStatus = Literal["open", "active", "closed", "archived"]

_MEMORY_SCOPES = {"portfolio", "company"}
_MEMORY_TYPES = {"note", "chat_memory", "watch_item", "embedding"}
_MEMORY_STATUSES = {"active", "archived", "consolidated"}
_MEMORY_SOURCE_TYPES = {"user", "chat"}
_RESEARCH_SESSION_STATUSES = {"open", "active", "closed", "archived"}


def _require_enum(value: str, allowed: set[str], field: str) -> str:
    if value not in allowed:
        raise HTTPException(
            status_code=400, detail=f"Invalid memory {field}"
        )
    return value


def _require_own_rows(
    db: Session,
    model: type[Claim] | type[Document],
    ids: list[int],
    company_id: int | None,
    label: str,
) -> None:
    """Los ids llegan del cliente y se guardan en JSON sin FK: sin esta
    comprobación se aceptaban ids inexistentes o de otro usuario. El select va
    acotado por tenant; con empresa, la fila tiene que ser de esa empresa."""
    wanted = set(ids)
    if not wanted:
        return
    statement = select(model.id).where(model.id.in_(wanted))
    if company_id is not None:
        statement = statement.where(
            (model.company_id == company_id) | (model.company_id.is_(None))
        )
    found = set(db.scalars(statement).all())
    if wanted - found:
        raise HTTPException(status_code=404, detail=f"{label} not found")


def validate_memory_item_enums(
    *, scope: str, memory_type: str, status: str, source_type: str
) -> None:
    """Valida los enums cerrados; lanza 400 fijo con mensaje fijo."""
    _require_enum(scope, _MEMORY_SCOPES, "scope")
    _require_enum(memory_type, _MEMORY_TYPES, "memory_type")
    _require_enum(status, _MEMORY_STATUSES, "status")
    _require_enum(source_type, _MEMORY_SOURCE_TYPES, "source_type")


def _company_by_ticker(db: Session, ticker: str) -> Company:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def _resolve_company_id(db: Session, ticker: str | None, company_id: int | None) -> int | None:
    if ticker:
        return _company_by_ticker(db, ticker).id
    if company_id is None:
        return None
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company.id


@router.get("/claims", response_model=list[ClaimOut])
def list_claims(
    ticker: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[Claim]:
    statement = select(Claim).options(selectinload(Claim.evidence))
    if ticker:
        company = _company_by_ticker(db, ticker)
        statement = statement.where(Claim.company_id == company.id)
    if status:
        statement = statement.where(Claim.status == status)
    return list(
        db.scalars(
            statement.order_by(desc(Claim.created_at))
            .offset((page - 1) * limit)
            .limit(limit)
        ).all()
    )


@router.post("/claims", response_model=ClaimOut)
def create_claim(payload: ClaimCreate, db: Session = Depends(get_db)) -> Claim:
    company_id = _resolve_company_id(db, payload.ticker, payload.company_id)
    thesis = db.get(ThesisVersion, payload.thesis_version_id) if payload.thesis_version_id else None
    if payload.thesis_version_id and thesis is None:
        raise HTTPException(status_code=404, detail="Thesis version not found")
    if thesis is not None:
        # Una afirmacion de A anclada a la tesis de B mezclaba ambas empresas
        # al contradecirla (el cambio de tesis iba a A con la version de B).
        if company_id is not None and thesis.company_id != company_id:
            raise HTTPException(
                status_code=422, detail="Thesis version belongs to another company"
            )
        company_id = thesis.company_id

    claim = Claim(
        company_id=company_id,
        thesis_version_id=payload.thesis_version_id,
        statement=payload.statement,
        claim_type=payload.claim_type,
        status=payload.status,
        confidence=payload.confidence,
        materiality_score=payload.materiality_score,
        source_quality=payload.source_quality,
        created_by=payload.created_by,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim


@router.get("/claims/{claim_id}", response_model=ClaimOut)
def get_claim(claim_id: int, db: Session = Depends(get_db)) -> Claim:
    claim = db.scalar(
        select(Claim).options(selectinload(Claim.evidence)).where(Claim.id == claim_id)
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


@router.post("/claims/{claim_id}/evidence", response_model=ClaimEvidenceOut)
def add_claim_evidence(
    claim_id: int, payload: ClaimEvidenceCreate, db: Session = Depends(get_db)
) -> ClaimEvidence:
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    document = db.get(Document, payload.document_id) if payload.document_id else None
    if payload.document_id and not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if payload.document_chunk_id:
        chunk = db.get(DocumentChunk, payload.document_chunk_id)
        if not chunk:
            raise HTTPException(status_code=404, detail="Document chunk not found")
        if payload.document_id and chunk.document_id != payload.document_id:
            raise HTTPException(status_code=400, detail="Document chunk does not belong to document")
        if payload.document_id is None:
            payload.document_id = chunk.document_id
            document = db.get(Document, chunk.document_id)
            if not document:
                raise HTTPException(status_code=404, detail="Document not found")

    source_tier = classify_source(
        document.source_type if document else "manual",
        document.source_url if document else payload.source_url,
    ).key

    evidence = ClaimEvidence(
        claim_id=claim.id,
        document_id=payload.document_id,
        document_chunk_id=payload.document_chunk_id,
        source_url=payload.source_url,
        evidence_type=payload.evidence_type,
        summary=payload.summary,
        quote=payload.quote,
        confidence=payload.confidence,
        source_tier=source_tier,
        metadata_={"source_tier_assigned_by": "backend"},
    )
    relation_status = {
        "contradicts": "contradicted",
        "supersedes": "superseded",
        "uncertain": "uncertain",
    }.get(payload.evidence_type)
    if relation_status:
        claim.status = relation_status
        change = ThesisChange(
            company_id=claim.company_id,
            from_version_id=claim.thesis_version_id,
            to_version_id=claim.thesis_version_id,
            change_type=claim_change_type(relation_status),
            impact_direction=(
                "negative" if relation_status == "contradicted" else "mixed"
            ),
            materiality_score=claim.materiality_score,
            summary=(
                f"La evidencia clasificó la afirmación como "
                f"{claim_status_label(relation_status)}: {claim.statement[:220]}"
            ),
            affected_claim_ids=[claim.id],
            affected_metrics=[],
            requires_review=True,
        )
        db.add(change)
        db.flush()
        ReviewAlertService().create_from_change(
            db,
            change,
            claim_id=claim.id,
            metadata={"manual_evidence": True, "source_tier": source_tier},
        )
    elif payload.evidence_type == "supports" and claim.status in {
        "unverified",
        "uncertain",
    }:
        claim.status = "supported"
    claim.last_reviewed_at = datetime.now(UTC)

    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


# «Qué ha cambiado» solo muestra cambios con relación fiable con la tesis.
_NO_RELIABLE_RELATION_MARKERS = (
    # Prefijos persistidos por el motor cuando NO encontro relacion (legacy y actual).
    "No structural thesis node matched with sufficient confidence.",
    "No stored thesis is available for semantic impact mapping.",
)


def _change_dedupe_key(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()[:200]


def _visible_thesis_changes(rows: list[ThesisChange], limit: int) -> list[ThesisChange]:
    """Filtra el feed de cambios: sin captacion de despachos, sin tarjetas sin
    relacion con la tesis y sin el mismo cambio repetido por ingesta multiple."""
    visible: list[ThesisChange] = []
    seen: set[str] = set()
    for row in rows:
        summary = row.summary or ""
        if is_law_firm_solicitation(summary):
            continue
        if any(marker in summary for marker in _NO_RELIABLE_RELATION_MARKERS):
            continue
        if not (row.affected_claim_ids or []) and not (row.affected_metrics or []):
            continue
        key = _change_dedupe_key(summary)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        visible.append(row)
        if len(visible) >= limit:
            break
    return visible


@router.get("/thesis/{ticker}/changes", response_model=list[ThesisChangeOut])
def list_thesis_changes(
    ticker: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[ThesisChange]:
    company = _company_by_ticker(db, ticker)
    # Sobremuestreo x4: el filtro de visibilidad descarta duplicados y tarjetas
    # sin relacion, y el limite debe aplicar a lo que la UI realmente muestra.
    rows = list(
        db.scalars(
            select(ThesisChange)
            .where(ThesisChange.company_id == company.id)
            .order_by(desc(ThesisChange.created_at))
            .limit(limit * 4)
        ).all()
    )
    return _visible_thesis_changes(rows, limit)


@router.post("/thesis/changes", response_model=ThesisChangeOut)
def create_thesis_change(payload: ThesisChangeCreate, db: Session = Depends(get_db)) -> ThesisChange:
    company_id = _resolve_company_id(db, payload.ticker, payload.company_id)
    for version_id, label in (
        (payload.from_version_id, "From"), (payload.to_version_id, "To"),
    ):
        if not version_id:
            continue
        version = db.get(ThesisVersion, version_id)
        if version is None:
            raise HTTPException(status_code=404, detail=f"{label} thesis version not found")
        # Mismo criterio que create_claim: no se mezcla la tesis de otra empresa.
        if company_id is not None and version.company_id != company_id:
            raise HTTPException(
                status_code=422, detail="Thesis version belongs to another company"
            )
        company_id = version.company_id

    change = ThesisChange(
        company_id=company_id,
        from_version_id=payload.from_version_id,
        to_version_id=payload.to_version_id,
        change_type=payload.change_type,
        impact_direction=payload.impact_direction,
        materiality_score=payload.materiality_score,
        summary=payload.summary,
        affected_claim_ids=payload.affected_claim_ids,
        affected_metrics=payload.affected_metrics,
        requires_review=payload.requires_review,
    )
    db.add(change)
    db.commit()
    db.refresh(change)
    return change


@router.get("/thesis/{ticker}/sections", response_model=list[ThesisSectionOut])
def list_thesis_sections(ticker: str, db: Session = Depends(get_db)) -> list[ThesisSection]:
    company = _company_by_ticker(db, ticker)
    latest = db.scalar(
        select(ThesisVersion)
        .where(ThesisVersion.company_id == company.id)
        .order_by(desc(ThesisVersion.version))
    )
    if not latest:
        raise HTTPException(status_code=404, detail="No thesis for ticker")
    return list(
        db.scalars(
            select(ThesisSection)
            .where(ThesisSection.thesis_version_id == latest.id)
            .order_by(ThesisSection.order_index, ThesisSection.section_key)
        ).all()
    )


@router.post(
    "/thesis/{ticker}/versions/{thesis_version_id}/sections",
    response_model=ThesisSectionOut,
)
def upsert_thesis_section(
    ticker: str,
    thesis_version_id: int,
    payload: ThesisSectionCreate,
    db: Session = Depends(get_db),
) -> ThesisSection:
    company = _company_by_ticker(db, ticker)
    thesis = db.scalar(
        select(ThesisVersion).where(
            ThesisVersion.id == thesis_version_id,
            ThesisVersion.company_id == company.id,
        )
    )
    if not thesis:
        raise HTTPException(status_code=404, detail="Thesis version not found")

    section = db.scalar(
        select(ThesisSection).where(
            ThesisSection.thesis_version_id == thesis.id,
            ThesisSection.section_key == payload.section_key,
        )
    )
    if not section:
        section = ThesisSection(
            thesis_version_id=thesis.id,
            company_id=company.id,
            section_key=payload.section_key,
        )
        db.add(section)

    section.title = payload.title
    section.body = payload.body
    section.status = payload.status
    section.order_index = payload.order_index
    section.confidence = payload.confidence

    db.commit()
    db.refresh(section)
    return section


@router.get("/research-sessions", response_model=list[ResearchSessionOut])
def list_research_sessions(
    ticker: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[ResearchSession]:
    statement = select(ResearchSession)
    if ticker:
        company = _company_by_ticker(db, ticker)
        statement = statement.where(ResearchSession.company_id == company.id)
    if status:
        statement = statement.where(ResearchSession.status == status)
    return list(db.scalars(statement.order_by(desc(ResearchSession.created_at)).limit(limit)).all())


@router.post("/research-sessions", response_model=ResearchSessionOut)
def create_research_session(
    payload: ResearchSessionCreate, db: Session = Depends(get_db)
) -> ResearchSession:
    _require_enum(payload.status, _RESEARCH_SESSION_STATUSES, "session status")
    company_id = _resolve_company_id(db, payload.ticker, payload.company_id)
    _require_own_rows(db, Claim, payload.claim_ids, company_id, "Claim")
    _require_own_rows(db, Document, payload.source_ids, company_id, "Source document")
    session = ResearchSession(
        company_id=company_id,
        title=payload.title,
        question=payload.question,
        status=payload.status,
        summary=payload.summary,
        source_ids=payload.source_ids,
        claim_ids=payload.claim_ids,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/memory-items", response_model=list[MemoryItemOut])
def list_memory_items(
    ticker: str | None = None,
    scope: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[MemoryItem]:
    if scope is not None:
        _require_enum(scope, _MEMORY_SCOPES, "scope")
    statement = select(MemoryItem)
    if ticker:
        company = _company_by_ticker(db, ticker)
        statement = statement.where(MemoryItem.company_id == company.id)
    if scope:
        statement = statement.where(MemoryItem.scope == scope)
    return list(db.scalars(statement.order_by(desc(MemoryItem.created_at)).limit(limit)).all())


@router.post("/memory-items", response_model=MemoryItemOut)
def create_memory_item(payload: MemoryItemCreate, db: Session = Depends(get_db)) -> MemoryItem:
    validate_memory_item_enums(
        scope=payload.scope,
        memory_type=payload.memory_type,
        status=payload.status,
        source_type=payload.source_type,
    )
    company_id = _resolve_company_id(db, payload.ticker, payload.company_id)
    session = db.get(ResearchSession, payload.research_session_id) if payload.research_session_id else None
    if payload.research_session_id and not session:
        raise HTTPException(status_code=404, detail="Research session not found")

    item = MemoryItem(
        company_id=company_id,
        research_session_id=payload.research_session_id,
        scope=payload.scope,
        memory_type=payload.memory_type,
        importance=payload.importance,
        content=payload.content,
        status=payload.status,
        source_type=payload.source_type,
        source_id=payload.source_id,
    )
    db.add(item)
    db.flush()
    if session:
        session.memory_item_ids = [*session.memory_item_ids, item.id]
    db.commit()
    db.refresh(item)
    return item
