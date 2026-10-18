import logging
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.models import Claim, ClaimEvidence, ThesisDiff, ThesisSection, ThesisVersion
from app.schemas import ThesisGenerateRequest, ThesisGraphOut, ThesisOut
from app.services.company_resolver import resolve_company
from app.services.driver_assumption_service import DriverAssumptionService, driver_assumption_payload
from app.services.provenance import Coverage, SourceKind, provenance
from app.services.thesis_approval_service import (
    DECISION_APPROVE,
    DECISION_REJECT,
    apply_approval_decision,
)
from app.services.thesis_epub_service import (
    EpubSection,
    ThesisEpubData,
    build_thesis_epub,
)
from app.services.thesis_graph_service import ThesisGraphService
from app.services.thesis_memo import build_memo_markdown
from app.services.thesis_service import ThesisService, latest_inputs_provenance, latest_missing_inputs

router = APIRouter()

_logger = logging.getLogger(__name__)


def _unknown_ticker(exc: Exception) -> bool:
    return "unknown ticker" in str(exc).lower()


def _safe_generate_error(exc: Exception) -> HTTPException:
    """Códigos fijos sin filtrar internos: ticker desconocido → 404 fijo,
    resto ValueError → 400 genérico, inesperado → 500 genérico. La causa
    real queda en el log con una referencia opaca."""
    if isinstance(exc, ValueError) and _unknown_ticker(exc):
        return HTTPException(status_code=404, detail="Company not found")
    # Sin tesis persistida no es un error de generacion: el contrato del
    # workspace es 404 para que el front pinte el estado vacio honesto.
    if isinstance(exc, ValueError) and str(exc).startswith("No thesis exists"):
        return HTTPException(status_code=404, detail="Thesis not found")
    ref = uuid4().hex[:8]
    _logger.exception("thesis generation failed (ref=%s)", ref)
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=400, detail=f"Thesis generation failed (ref {ref})"
        )
    return HTTPException(
        status_code=500, detail=f"Thesis generation failed (ref {ref})"
    )


@router.post("/generate", response_model=ThesisOut)
def generate_thesis(payload: ThesisGenerateRequest, db: Session = Depends(get_db)) -> dict:
    try:
        thesis = ThesisService().generate(db, payload.ticker, payload.force_new_version)
    except Exception as exc:
        raise _safe_generate_error(exc) from exc
    out = ThesisOut.model_validate(thesis).model_dump()
    out["missing_inputs"] = latest_missing_inputs(db, thesis.company_id)
    out["inputs_provenance"] = latest_inputs_provenance(
        db, thesis.company_id, thesis.valuation_basis
    )
    return out



class ThesisHumanInput(BaseModel):
    """Explicit human assumptions, never promoted to sourced financial facts."""

    driver_key: str = Field(min_length=1, max_length=160)
    fiscal_year: int = Field(ge=1900, le=2200)
    scenario: Literal["bear", "base", "bull"] = "base"
    value: Decimal = Field(allow_inf_nan=False)
    source: str = Field(min_length=1, max_length=240)
    confidence: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=5000)


class ThesisInputsRequest(BaseModel):
    inputs: list[ThesisHumanInput] = Field(min_length=1, max_length=30)


@router.post("/{ticker}/inputs", status_code=201)
def submit_thesis_inputs(
    ticker: str, payload: ThesisInputsRequest, db: Session = Depends(get_db)
) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if db.info.get("tenant_id") is None:
        raise HTTPException(status_code=403, detail="Tenant context required")
    rows = []
    # A bad later input must not leave earlier assumptions committed.
    try:
        with db.begin_nested():
            for item in payload.inputs:
                version = DriverAssumptionService().create(
                    db, company, **item.model_dump(), user_override=True, commit=False
                )
                rows.append(driver_assumption_payload(version, driver_key=item.driver_key))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Unknown driver; build the company model first") from exc
    db.commit()
    return {
        "ticker": company.ticker,
        "inputs": rows,
        "provenance_label": "supuesto",
        "requires_regeneration": True,
    }

def _epub_citations(db: Session, claims: list[Claim]) -> list[str]:
    """Citas del EPUB con provenance real (source_id + locator).

    Cada cita conserva el statement pero siempre lleva su localizador:
    claim -> evidence -> document/document_chunk (+ tier y URL cuando
    existen). Sin evidencia vinculada se declara explicitamente en vez
    de inventar una fuente.
    """
    live = [c for c in claims if c.statement]
    if not live:
        return []
    evidence = list(
        db.scalars(
            select(ClaimEvidence).where(
                ClaimEvidence.claim_id.in_([c.id for c in live])
            )
        ).all()
    )
    by_claim: dict[int, list[ClaimEvidence]] = {}
    for row in evidence:
        by_claim.setdefault(row.claim_id, []).append(row)
    citations: list[str] = []
    for claim in live:
        rows = by_claim.get(claim.id, [])
        if not rows:
            citations.append(f"{claim.statement} [claim:{claim.id} · sin evidencia vinculada]")
            continue
        for row in rows:
            locator = f"evidence:{row.id}"
            if row.document_id is not None:
                locator += f" · doc:{row.document_id}"
            if row.document_chunk_id is not None:
                locator += f" · chunk:{row.document_chunk_id}"
            if row.source_url:
                locator += f" · {row.source_url}"
            citations.append(
                f"{claim.statement} [claim:{claim.id} → {locator} · {row.evidence_type} · {row.source_tier}]"
            )
    return citations


@router.get("/{ticker}/epub")
def thesis_epub(ticker: str, db: Session = Depends(get_db)) -> Response:
    """Descarga la última tesis como EPUB (e-reader/Kindle).

    404 limpio cuando no hay tesis: nunca se genera un documento vacío.
    """
    company = resolve_company(db, ticker)
    thesis = (
        db.scalar(
            select(ThesisVersion)
            .where(ThesisVersion.company_id == company.id)
            .order_by(desc(ThesisVersion.version))
            .limit(1)
        )
        if company
        else None
    )
    if thesis is None:
        raise HTTPException(status_code=404, detail="No thesis for ticker")
    sections = db.scalars(
        select(ThesisSection)
        .where(ThesisSection.thesis_version_id == thesis.id)
        .order_by(ThesisSection.order_index)
    ).all()
    claims = db.scalars(
        select(Claim).where(Claim.thesis_version_id == thesis.id)
    ).all()
    data = ThesisEpubData(
        ticker=company.ticker,
        company_name=company.name or "",
        version=thesis.version,
        rating=thesis.rating or "watch",
        status=thesis.status or "draft",
        generated_on=thesis.updated_at.date().isoformat() if thesis.updated_at else "",
        executive_summary=thesis.executive_summary or "",
        sections=[EpubSection(title=s.title, body=s.body or "") for s in sections],
        citations=_epub_citations(db, list(claims)),
    )
    content = build_thesis_epub(data)
    filename = f"gerarai-thesis-{company.ticker}-v{thesis.version}.epub"
    return Response(
        content=content,
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{ticker}/latest", response_model=ThesisOut)
def latest_thesis(ticker: str, db: Session = Depends(get_db)) -> dict:
    service = ThesisService()
    thesis = service.latest(db, ticker)
    if not thesis:
        raise HTTPException(status_code=404, detail="No thesis for ticker")
    # Senal de frescura: hay datos mas nuevos que esta version (hechos,
    # precios, noticias o documentos) -> conviene regenerar la tesis.
    latest_data_at = service.data_freshness(db, thesis.company_id)
    stale = latest_data_at is not None and latest_data_at > thesis.updated_at
    payload = ThesisOut.model_validate(thesis).model_dump()
    payload["stale"] = stale
    payload["latest_data_at"] = latest_data_at
    payload["missing_inputs"] = latest_missing_inputs(db, thesis.company_id)
    payload["inputs_provenance"] = latest_inputs_provenance(
        db, thesis.company_id, thesis.valuation_basis
    )
    return payload


@router.get("/{ticker}/versions", response_model=list[ThesisOut])
def thesis_versions(
    ticker: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[ThesisVersion]:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return list(
        db.scalars(
            select(ThesisVersion)
            .where(ThesisVersion.company_id == company.id)
            .order_by(desc(ThesisVersion.version))
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )


@router.get("/{ticker}/history")
def thesis_history(ticker: str, db: Session = Depends(get_db)) -> dict:
    """Historial de versiones/aprobaciones: que cambio, cuando y con que resultado.

    Solo lectura de lo persistido (versions + diffs). El "quien" no se
    registra hoy: el historial muestra estado, fecha y resumen del cambio,
    sin inventar actores.
    """
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    versions = list(
        db.scalars(
            select(ThesisVersion)
            .where(ThesisVersion.company_id == company.id)
            .order_by(desc(ThesisVersion.version))
            .limit(50)
        ).all()
    )
    diffs = {
        diff.to_version_id: diff
        for diff in db.scalars(
            select(ThesisDiff).where(ThesisDiff.company_id == company.id)
        ).all()
        if diff.to_version_id is not None
    }
    items = []
    for version in versions:
        diff = diffs.get(version.id)
        items.append(
            {
                "id": version.id,
                "version": version.version,
                "status": version.status,
                "rating": version.rating,
                "red_team_score": version.red_team_score,
                "data_confidence_score": version.data_confidence_score,
                "created_at": version.created_at.isoformat(),
                "updated_at": version.updated_at.isoformat(),
                "diff": (
                    {
                        "change_summary": diff.change_summary,
                        "affected_assumptions": diff.affected_assumptions,
                        "rating_changed": diff.rating_changed,
                        "created_at": diff.created_at.isoformat(),
                    }
                    if diff
                    else None
                ),
            }
        )
    latest_at = versions[0].created_at.isoformat() if versions else None
    return {
        "ticker": company.ticker,
        "count": len(items),
        "history": items,
        "data_as_of": latest_at,
        "provenance": provenance(
            "CavaAI Postgres",
            SourceKind.INTERNAL,
            coverage=Coverage.OK if versions else Coverage.UNAVAILABLE,
            note="Historial calculado desde versiones y diffs persistidos; sin actores inventados.",
        ),
    }


@router.get("/{ticker}/memo.md", response_class=PlainTextResponse)
def thesis_memo(ticker: str, db: Session = Depends(get_db)) -> PlainTextResponse:
    """Memo Markdown descargable de la ultima tesis persistida."""
    service = ThesisService()
    thesis = service.latest(db, ticker)
    if not thesis:
        raise HTTPException(status_code=404, detail="No thesis for ticker")
    company = resolve_company(db, ticker)
    latest_data_at = service.data_freshness(db, thesis.company_id)
    stale = latest_data_at is not None and latest_data_at > thesis.updated_at
    markdown = build_memo_markdown(db, company, thesis, stale=stale, latest_data_at=latest_data_at)
    return PlainTextResponse(
        markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="tesis-{company.ticker.lower()}-v{thesis.version}.md"'
        },
    )


@router.get("/{ticker}/graph", response_model=ThesisGraphOut)
def thesis_graph(ticker: str, db: Session = Depends(get_db)) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    try:
        thesis, nodes, edges = ThesisGraphService().read(db, company)
    except ValueError as exc:
        if _unknown_ticker(exc):
            raise HTTPException(status_code=404, detail="Company not found") from exc
        raise _safe_generate_error(exc) from exc
    return {
        "ticker": company.ticker,
        "thesis_version_id": thesis.id,
        "nodes": nodes,
        "edges": edges,
    }


@router.post("/{ticker}/graph/refresh", response_model=ThesisGraphOut)
def refresh_thesis_graph(ticker: str, db: Session = Depends(get_db)) -> dict:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    try:
        thesis, nodes, edges = ThesisGraphService().build(db, company)
    except ValueError as exc:
        if _unknown_ticker(exc):
            raise HTTPException(status_code=404, detail="Company not found") from exc
        raise _safe_generate_error(exc) from exc
    return {
        "ticker": company.ticker,
        "thesis_version_id": thesis.id,
        "nodes": nodes,
        "edges": edges,
    }


@router.post("/{ticker}/debate")
async def debate_thesis_endpoint(ticker: str, db: Session = Depends(get_db)) -> dict:
    """Debate bull/bear sobre la última tesis y persiste el veredicto.

    El debate en sí nunca lanza (degrada a veredicto determinista); si el
    upsert de la sección falla, se devuelve el debate con persisted=False.
    """
    from app.services.thesis_debate_service import debate_thesis

    # Lecturas sqlalchemy sincronas fuera del event loop (el debate LLM si
    # es async real y se queda awaitado).
    thesis = await run_in_threadpool(ThesisService().latest, db, ticker)
    if not thesis:
        raise HTTPException(status_code=404, detail="No thesis for ticker")
    company = await run_in_threadpool(resolve_company, db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    try:
        result = await debate_thesis(
            company.ticker,
            thesis.thesis_markdown or thesis.executive_summary or "",
            db=db,
        )
    except Exception:  # noqa: BLE001 — sin provider LLM: veredicto determinista
        from app.services.thesis_debate_service import _deterministic_verdict

        fallback = _deterministic_verdict(company.ticker, thesis.thesis_markdown or "", "", "")
        result = {
            "ticker": company.ticker,
            "bull_case": "",
            "bear_case": "",
            "verdict": fallback["verdict"],
            "verdict_rationale": fallback["verdict_rationale"],
            "llm_calls": 0,
            "degraded": True,
            "model": "deterministic",
            "materiality_score": 0,
            "portfolio_weight": 0.0,
        }
    def _persist_verdict() -> bool:
        try:
            section = db.scalar(
                select(ThesisSection).where(
                    ThesisSection.thesis_version_id == thesis.id,
                    ThesisSection.section_key == "thesis_debate",
                )
            )
            if section is None:
                section = ThesisSection(
                    thesis_version_id=thesis.id,
                    company_id=company.id,
                    section_key="thesis_debate",
                    title="Thesis debate (bull vs bear)",
                    status="published",
                    order_index=999,
                )
                db.add(section)
            section.body = f"VEREDICTO: {result['verdict']} | {result['verdict_rationale']}"
            section.metadata_ = {
                "bull_case": result["bull_case"],
                "bear_case": result["bear_case"],
                "verdict": result["verdict"],
                "verdict_rationale": result["verdict_rationale"],
                "llm_calls": result["llm_calls"],
                "degraded": result["degraded"],
                "model": result["model"],
            }
            db.commit()
            return True
        except Exception:  # noqa: BLE001 — el debate ya existe; persistir es best-effort
            db.rollback()
            return False

    # El upsert del veredicto es escritura sqlalchemy sincrona: hilo del pool.
    persisted = await run_in_threadpool(_persist_verdict)
    return {
        "ticker": company.ticker,
        "thesis_version_id": thesis.id,
        "persisted": persisted,
        **result,
    }


class ThesisApproveRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    actor: str = Field(default="user", min_length=1, max_length=160)


@router.post("/{ticker}/approve")
def approve_thesis(ticker: str, payload: ThesisApproveRequest, db: Session = Depends(get_db)) -> dict:
    """Aprueba o rechaza la ultima tesis persistida del ticker.

    Transicion de estado honesta sobre lo persistido (status + updated_at);
    el actor se registra en el log y se devuelve en la respuesta, pero hoy
    no existe columna de actor en thesis_versions: la auditoria por actor
    queda documentada como trabajo futuro. La aprobacion automatica por
    Telegram (TELEGRAM_APPROVAL_ENABLED) tampoco esta cableada a este
    endpoint: solo la pulsacion manual en la UI cambia el estado.
    """
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    thesis = (
        db.scalar(
            select(ThesisVersion)
            .where(ThesisVersion.company_id == company.id)
            .order_by(desc(ThesisVersion.version))
            .limit(1)
        )
    )
    if thesis is None:
        raise HTTPException(status_code=404, detail="No thesis for ticker")
    # Delegate to the same transition function the Telegram poller uses. The
    # route used to assign `thesis.status = payload.decision` directly, with no
    # state check and a different vocabulary, so an `insufficient_data` or
    # `draft_failed_audit` version could be marked approved while its own memo
    # said "NO VALUATION".
    try:
        thesis = apply_approval_decision(
            db,
            thesis.id,
            DECISION_APPROVE if payload.decision == "approved" else DECISION_REJECT,
            via="api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.refresh(thesis)
    _logger.info(
        "thesis %s v%s %s by actor=%s", company.ticker, thesis.version, payload.decision, payload.actor
    )
    return {
        "ticker": company.ticker,
        "thesis_version_id": thesis.id,
        "version": thesis.version,
        "status": thesis.status,
        "decision": payload.decision,
        "actor": payload.actor,
        "approved_at": thesis.updated_at.isoformat(),
        "telegram_auto_approval": "future",
        "provenance": provenance(
            "CavaAI Postgres",
            SourceKind.INTERNAL,
            coverage=Coverage.OK,
            note="Transicion de estado manual; sin aprobacion automatica por Telegram.",
        ),
    }


@router.post("/generate-async", status_code=202)
def generate_thesis_async(payload: ThesisGenerateRequest, db: Session = Depends(get_db)) -> dict:
    """Enqueue background thesis generation (durable job envelope).

    Returns 202 with the job state; poll GET /api/thesis/jobs/{id} for honest
    phase progress. Re-posting the same ticker+force while active returns the
    existing job (idempotent).
    """
    from app.services.thesis_job_service import enqueue_generation, job_payload

    run, _created = enqueue_generation(
        db, payload.ticker, payload.force_new_version, payload.request_id
    )
    return job_payload(run)


@router.get("/jobs/{run_id}")
def thesis_job_status(run_id: int, db: Session = Depends(get_db)) -> dict:
    from app.models.entities import WorkflowRun
    from app.services.thesis_job_service import WORKFLOW_NAME, job_payload

    run = db.get(WorkflowRun, run_id)
    if run is None or run.workflow_name != WORKFLOW_NAME:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_payload(run)


@router.get("/jobs")
def latest_thesis_job(ticker: str = Query(min_length=1, max_length=20), db: Session = Depends(get_db)) -> dict:
    """Recover the user's latest active/completed generation after navigation."""
    from app.services.thesis_job_service import job_payload, latest_generation

    run = latest_generation(db, ticker, active_only=True) or latest_generation(db, ticker)
    return {"job": job_payload(run) if run is not None else None}
