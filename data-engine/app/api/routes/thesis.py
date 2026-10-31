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
from app.core.ui_errors import ui_error
from app.models import Claim, ClaimEvidence, ThesisDiff, ThesisSection, ThesisVersion
from app.schemas import ThesisGenerateRequest, ThesisGraphOut, ThesisOut
from app.schemas.api import (
    ThesisAudioStatusOut,
    ThesisHistoryOut,
    ThesisJobStatusOut,
    ThesisLatestJobOut,
)
from app.services import thesis_audio_service
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
from app.services.thesis_pdf_service import export_thesis_pdf_for_ticker, sanitize_pdf_filename
from app.services.thesis_publication_gate import (
    archived_thesis_notice,
    thesis_withheld_reason,
    thesis_withheld_reasons,
    withhold_thesis_payload,
)
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
    out = withhold_thesis_payload(ThesisOut.model_validate(thesis).model_dump(), thesis, thesis_withheld_reason(db, thesis))
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
    reason = thesis_withheld_reason(db, thesis)
    data = ThesisEpubData(
        ticker=company.ticker,
        company_name=company.name or "",
        version=thesis.version,
        rating="insufficient_data" if reason else thesis.rating or "watch",
        status=thesis.status or "draft",
        generated_on=thesis.updated_at.date().isoformat() if thesis.updated_at else "",
        executive_summary=archived_thesis_notice(thesis, reason) if reason else thesis.executive_summary or "",
        sections=[] if reason else [EpubSection(title=s.title, body=s.body or "") for s in sections],
        citations=[] if reason else _epub_citations(db, list(claims)),
    )
    content = build_thesis_epub(data)
    # Mismo saneado que el PDF: el ticker va a una cabecera Content-Disposition.
    filename = f"gerarai-thesis-{sanitize_pdf_filename(company.ticker)}-v{thesis.version}.epub"
    return Response(
        content=content,
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{ticker}/pdf")
def thesis_pdf(ticker: str, db: Session = Depends(get_db)) -> Response:
    """Descarga la última tesis como PDF con diseño profesional y branding GerarAI.

    404 limpio cuando no hay tesis: nunca se genera un documento vacío.
    """
    try:
        content, filename = export_thesis_pdf_for_ticker(db, ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return Response(
        content=content,
        media_type="application/pdf",
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
    latest_data_at = service.data_freshness(db, thesis.company_id, as_of=thesis.updated_at)
    stale = latest_data_at is not None and latest_data_at > thesis.updated_at
    payload = withhold_thesis_payload(ThesisOut.model_validate(thesis).model_dump(), thesis, thesis_withheld_reason(db, thesis))
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
) -> list[dict]:
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    versions = list(
        db.scalars(
            select(ThesisVersion)
            .where(ThesisVersion.company_id == company.id)
            .order_by(desc(ThesisVersion.version))
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    reasons = thesis_withheld_reasons(db, versions)
    return [withhold_thesis_payload(ThesisOut.model_validate(row).model_dump(), row, reasons[row.id])
            for row in versions]


@router.get("/{ticker}/history", response_model=ThesisHistoryOut,
                    response_model_exclude_unset=True)
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
            .limit(51)
        ).all()
    )
    # La version 51 solo sirve de anterior para derivar el diff de la 50.
    previous_by_id = {
        version.id: versions[index + 1] if index + 1 < len(versions) else None
        for index, version in enumerate(versions)
    }
    versions = versions[:50]
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
                    else derived_thesis_diff(previous_by_id.get(version.id), version)
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
            "Base de datos de GerarAI",
            SourceKind.INTERNAL,
            coverage=Coverage.OK if versions else Coverage.UNAVAILABLE,
            note="Historial calculado desde versiones y diffs persistidos; sin actores inventados.",
        ),
    }


def _pct_change(old, new) -> float | None:
    if old in (None, 0) or new is None:
        return None
    return (float(new) - float(old)) / abs(float(old)) * 100


def derived_thesis_diff(previous, current) -> dict | None:
    """Diff determinista entre dos versiones consecutivas (nada lo persiste hoy).

    Solo compara campos guardados: calificacion, escenarios y puntuaciones. Sin
    version anterior no hay diff (primera version)."""
    if previous is None:
        return None
    parts: list[str] = []
    rating_changed = previous.rating != current.rating
    if rating_changed:
        parts.append("cambia la calificación")
    for label, old, new in (
        ("bajista", previous.bear_value, current.bear_value),
        ("base", previous.base_value, current.base_value),
        ("alcista", previous.bull_value, current.bull_value),
    ):
        change = _pct_change(old, new)
        if change is not None and abs(change) >= 0.5:
            parts.append(f"escenario {label} {change:+.1f} %".replace(".", ","))
    for label, old, new in (
        ("confianza de datos", previous.data_confidence_score, current.data_confidence_score),
        ("cobertura de fuentes", previous.source_coverage_score, current.source_coverage_score),
        ("red team", previous.red_team_score, current.red_team_score),
    ):
        if old != new:
            parts.append(f"{label} {old} → {new}")
    summary = (
        "Cambios frente a la versión anterior: " + "; ".join(parts) + "."
        if parts
        else "Sin cambios materiales (±0,5 %) en calificación, escenarios ni puntuaciones frente a la versión anterior."
    )
    return {
        "change_summary": summary,
        "affected_assumptions": [],
        "rating_changed": rating_changed,
        "created_at": current.created_at.isoformat(),
        "derived": True,
    }


@router.get("/{ticker}/memo.md", response_class=PlainTextResponse)
def thesis_memo(
    ticker: str,
    published: bool = Query(False),
    draft: bool = Query(False),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Memo Markdown descargable de la ultima tesis persistida.

    Con ``published=1`` la version es la ultima PUBLICADA (regla vigente: un
    borrador no enseña cifras ni margen); sin el parametro se conserva el
    comportamiento historico (ultima version, sea cual sea su estado).
    ``draft=1`` devuelve la version de borrador sin veredicto, hipotesis,
    resumen, valoracion ni secciones (ver ``build_memo_markdown``).
    """
    service = ThesisService()
    if published:
        company = resolve_company(db, ticker)
        thesis = (
            db.scalar(
                select(ThesisVersion)
                .where(
                    ThesisVersion.company_id == company.id,
                    ThesisVersion.status == "published",
                )
                .order_by(desc(ThesisVersion.version))
                .limit(1)
            )
            if company
            else None
        )
        if thesis is None:
            raise HTTPException(status_code=404, detail="No published thesis for ticker")
    else:
        thesis = service.latest(db, ticker)
    if not thesis:
        raise HTTPException(status_code=404, detail="No thesis for ticker")
    company = resolve_company(db, ticker)
    latest_data_at = service.data_freshness(db, thesis.company_id, as_of=thesis.updated_at)
    stale = latest_data_at is not None and latest_data_at > thesis.updated_at
    markdown = build_memo_markdown(
        db, company, thesis, stale=stale, latest_data_at=latest_data_at, draft=draft
    )
    return PlainTextResponse(
        markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="tesis-{company.ticker.lower()}-v{thesis.version}.md"'
        },
    )


def _audio_context(db: Session, ticker: str, version: int | None = None) -> tuple[str, str]:
    """(key, texto hablable) de la version que corresponde locutar.

    Por defecto suena la ultima tesis PUBLICADA vigente: un borrador nunca
    se locuta solo por ser la ultima version (v13 borrador no tapa a v11
    publicada). Sin publicada hay 404. Con ``version=N`` se pide una version
    concreta; si no esta publicada se mantiene el modo borrador del memo
    (sin veredicto ni cifras).
    """
    service = ThesisService()
    if version is None:
        thesis = service.latest_published(db, ticker)
        if not thesis:
            raise HTTPException(status_code=404, detail="No published thesis for ticker")
    else:
        thesis = service.by_version(db, ticker, version)
        if not thesis:
            raise HTTPException(status_code=404, detail=f"No thesis version {version} for ticker")
    company = resolve_company(db, ticker)
    latest_data_at = service.data_freshness(db, thesis.company_id, as_of=thesis.updated_at)
    stale = latest_data_at is not None and latest_data_at > thesis.updated_at
    # Un borrador no puede locutar veredicto, margen de seguridad ni valoracion:
    # mismo modo borrador que memo.md?draft=1.
    is_draft = (thesis.status or "draft") != "published"
    markdown = build_memo_markdown(
        db, company, thesis, stale=stale, latest_data_at=latest_data_at, draft=is_draft
    )
    text = thesis_audio_service.memo_to_speech_text(markdown, ticker=company.ticker, version=thesis.version)
    key = thesis_audio_service.audio_key(
        company.ticker,
        thesis.version,
        draft=is_draft,
        data_day=thesis_audio_service.data_day(latest_data_at),
    )
    # Never serve a previously cached narration of the archived valuation.
    if thesis_withheld_reason(db, thesis):
        key += "-withheld-v1"
    return key, text


@router.get("/{ticker}/audio/status", response_model=ThesisAudioStatusOut,
                    response_model_exclude_unset=True)
def thesis_audio_status(
    ticker: str,
    version: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
) -> dict:
    """Estado del audio: ready | pending | missing | unavailable | error.

    Por defecto, de la ultima tesis PUBLICADA; si no hay ninguna devuelve
    ``missing`` (no 404) para que la ficha muestre «sin audio» en vez de un
    error. ``?version=N`` consulta una version concreta (404 si no existe).
    """
    try:
        key, _ = _audio_context(db, ticker, version)
    except HTTPException as exc:
        if version is None and exc.status_code == 404:
            return {"state": "missing", "key": None}
        raise
    return {**thesis_audio_service.status_info(key), "key": key}


@router.post("/{ticker}/audio", status_code=202)
def thesis_audio_generate(
    ticker: str,
    version: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
) -> dict:
    """Encola la generacion (idempotente); si ya esta listo devuelve ready.

    Por defecto genera la ultima PUBLICADA (404 si no hay: nunca se locuta
    un borrador por omision). ``?version=N`` genera esa version; una no
    publicada suena en modo borrador, sin veredicto ni cifras.
    """
    key, text = _audio_context(db, ticker, version)
    current = thesis_audio_service.status(key)
    if current in ("ready", "pending"):
        # Una sintesis a la vez por tesis: no se reencola mientras haya una en curso.
        return {"state": current, "key": key}
    state = thesis_audio_service.start(key, text)
    if state == "unavailable":
        raise HTTPException(status_code=503, detail="Servicio de audio no disponible")
    return {"state": state, "key": key}


@router.get("/{ticker}/audio")
def thesis_audio(
    ticker: str,
    version: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
) -> Response:
    """El mp3 cacheado; 404 si aun no esta generado o la version no existe.

    Misma seleccion que POST: ultima PUBLICADA por defecto, ``?version=N``
    para una concreta.
    """
    key, _ = _audio_context(db, ticker, version)
    data = thesis_audio_service.fetch_mp3(key)
    if data is None:
        raise HTTPException(status_code=404, detail="Audio no generado")
    return Response(
        content=data,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=3600", "Content-Disposition": f'inline; filename="{key}.mp3"'},
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

    Sin LLM gratuito se devuelve 503, nunca se persiste un debate inventado.
    Si el upsert falla, se devuelve el debate con persisted=False.
    """
    from app.services.thesis_debate_service import debate_thesis

    # Lecturas sqlalchemy sincronas fuera del event loop (el debate LLM si
    # es async real y se queda awaitado).
    thesis = await run_in_threadpool(ThesisService().latest, db, ticker)
    if not thesis:
        raise HTTPException(status_code=404, detail="No thesis for ticker")
    reason = await run_in_threadpool(thesis_withheld_reason, db, thesis)
    if reason:
        raise HTTPException(status_code=409, detail=archived_thesis_notice(thesis, reason))
    company = await run_in_threadpool(resolve_company, db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    import asyncio

    from app.llm.errors import LLMError
    from app.llm.free_interactive import FreeLLMUnavailable, create_free_interactive_provider
    from app.services.budget import BudgetExceededError

    try:
        # One deadline for bull, bear, judge and output-guard retries together.
        result = await asyncio.wait_for(debate_thesis(
            company.ticker,
            thesis.thesis_markdown or thesis.executive_summary or "",
            provider=create_free_interactive_provider(),
            use_jev=False,  # Jev is metered, not part of the zero-cost chain.
            strict_provider=True,
            db=db,
        ), timeout=45)
    except FreeLLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except TimeoutError:
        raise ui_error(503, "debate_timeout") from None
    except BudgetExceededError:
        raise ui_error(503, "llm_budget_exhausted") from None
    except (LLMError, ValueError):
        raise ui_error(503, "debate_invalid_response") from None
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


class InvalidationRuleIn(BaseModel):
    metric: str = Field(..., max_length=130)
    operator: Literal[">", "<", ">=", "<=", "==", "!="]
    threshold: float | str
    description: str | None = Field(default=None, max_length=300)


class InvalidationRulesRequest(BaseModel):
    rules: list[InvalidationRuleIn] = Field(default_factory=list, max_length=20)


@router.put("/{ticker}/invalidation-rules")
def set_invalidation_rules(
    ticker: str, payload: InvalidationRulesRequest, db: Session = Depends(get_db)
) -> dict:
    """Guarda los criterios MEDIBLES de invalidacion en la ultima tesis.

    Cada criterio (metrica, operador, umbral) queda vigilado por el evaluador
    de alertas: cuando se cumple, llega un aviso. Lista vacia = sin criterios
    (las reglas de aviso derivadas se desactivan). Los criterios se conservan
    al regenerar la tesis.
    """
    from app.services.thesis_invalidation_rules import (
        describe_rule,
        normalize_rules,
        sync_thesis_rules,
    )

    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    thesis = db.scalar(
        select(ThesisVersion)
        .where(ThesisVersion.company_id == company.id)
        .order_by(desc(ThesisVersion.version))
        .limit(1)
    )
    if thesis is None:
        raise HTTPException(status_code=404, detail="No thesis for ticker")
    try:
        rules = normalize_rules([rule.model_dump() for rule in payload.rules])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    thesis.invalidation_rules = rules or None
    db.flush()
    alert_rules = sync_thesis_rules(db, company)
    db.commit()
    return {
        "ticker": company.ticker,
        "thesis_version_id": thesis.id,
        "version": thesis.version,
        "invalidation_rules": [{**rule, "label": describe_rule(rule)} for rule in rules],
        "alert_rule_ids": [rule.id for rule in alert_rules],
    }


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
    side_effects: dict = {}
    try:
        thesis = apply_approval_decision(
            db,
            thesis.id,
            DECISION_APPROVE if payload.decision == "approved" else DECISION_REJECT,
            via="api",
            out=side_effects,
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
        # Resultado real del indexado en la Biblioteca (RAG): indexed /
        # unchanged / removed / none / failed. Nunca inventado por la UI.
        "knowledge_sync": side_effects.get("knowledge_sync"),
        "provenance": provenance(
            "Base de datos de GerarAI",
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


@router.get("/jobs/{run_id}", response_model=ThesisJobStatusOut)
def thesis_job_status(run_id: int, db: Session = Depends(get_db)) -> dict:
    from app.models.entities import WorkflowRun
    from app.services.thesis_job_service import WORKFLOW_NAME, job_payload

    run = db.get(WorkflowRun, run_id)
    if run is None or run.workflow_name != WORKFLOW_NAME:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_payload(run)


@router.get("/jobs", response_model=ThesisLatestJobOut)
def latest_thesis_job(ticker: str = Query(min_length=1, max_length=20), db: Session = Depends(get_db)) -> dict:
    """Recover the user's latest active/completed generation after navigation."""
    from app.services.thesis_job_service import job_payload, latest_generation

    run = latest_generation(db, ticker, active_only=True) or latest_generation(db, ticker)
    return {"job": job_payload(run) if run is not None else None}
