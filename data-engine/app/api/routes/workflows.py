from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import safe_detail
from app.core.local_date import local_today
from app.core.tenancy import tenant_filters
from app.models import Company
from app.models.entities import WorkflowRun
from app.services.async_bridge import run_from_any_context
from app.services.workflow_run_service import WorkflowEnvelope, begin_run
from app.workflows.catalog import (
    RETIRED_WORKFLOWS,
    WORKFLOW_CATALOG,
    find_retired,
    find_workflow,
)

router = APIRouter()

# Status codes of POST /api/workflows/{name}/run (see README of this module):
#   200 the workflow really executed (or replayed a stored result)
#   404 unknown workflow; for a retired one the detail says why and what replaced it
#   422 the workflow is executable but its required input is missing
#   501 the workflow is in the catalog but has no execution route via the API
#   500 the work itself failed; the detail never claims "queued"


class WorkflowRunRequest(BaseModel):
    ticker: str | None = None
    params: dict = Field(default_factory=dict)


class EarningsRunParams(BaseModel):
    """Params validados de EarningsWorkflow.

    Antes el handler coaccionaba en silencio dentro del paso MAF:
    ``bool("false")`` es True (un ``"false"`` en JSON forzaba una tesis
    nueva), ``int(2024.9)`` truncaba y ``str(2024)`` aceptaba un entero
    como trimestre; ademas el envelope grababa los params crudos, no los
    valores ejecutados. Aqui se valida una sola vez: lo invalido es 422
    antes de abrir el run y el envelope graba exactamente lo que corre.
    """

    # Año del usuario (Europe/Madrid), no el del reloj UTC del servidor.
    fiscal_year: int = Field(default_factory=lambda: local_today().year)
    fiscal_quarter: str = "FY"
    document_ids: list[int] = Field(default_factory=list)
    force_new_thesis: bool = False


def _params_422(exc: ValidationError, *, context: str) -> HTTPException:
    """422 con los errores de pydantic del propio payload del cliente."""
    return HTTPException(
        status_code=422,
        detail={
            "error": context,
            "fields": [
                {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
                for error in exc.errors()
            ],
        },
    )


@router.get("")
def workflows() -> dict:
    # Sin docstring a proposito: FastAPI lo copia a OpenAPI como `description`
    # y el job openapi-drift regenera el contrato. La verdad del catalogo va
    # en los propios campos (implementation_status + api_executable) y en
    # `retired_workflows`, que es la parte aditiva: los nombres retirados ya no
    # se ejecutan aqui y la API lo dice en vez de devolver un 200 vacío.
    return {"workflows": WORKFLOW_CATALOG, "retired_workflows": RETIRED_WORKFLOWS}


def _unknown_workflow(name: str) -> HTTPException:
    retired = find_retired(name)
    if retired is not None:
        return HTTPException(
            status_code=404,
            detail=(
                f"Workflow '{name}' was retired from the catalog: {retired['reason']} "
                f"Use {retired['replaced_by']} instead."
            ),
        )
    return HTTPException(status_code=404, detail=f"Workflow '{name}' not found")


@router.get("/{name}")
def get_workflow(name: str) -> dict:
    workflow = find_workflow(name)
    if not workflow:
        raise _unknown_workflow(name)
    return workflow


def _require_ticker(payload: WorkflowRunRequest, name: str) -> str:
    """Ticker is a required input of these workflows; say so instead of faking a run."""
    ticker = (payload.ticker or "").strip().upper()
    if not ticker:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Workflow '{name}' requires a ticker. POST /run executes this workflow "
                "for real; nothing runs without its input."
            ),
        )
    return ticker


def _replay_response(envelope: WorkflowEnvelope, workflow: dict, ticker: str | None) -> dict:
    """Stored result for an idempotent re-delivery; the work does not run twice."""
    stored = dict(envelope.run.result_payload or {})
    return {
        **stored,
        "run_id": envelope.run.id,
        "idempotent_replay": True,
        "steps": workflow["steps"],
        "estimated_minutes": 0,
        "workflow": workflow["name"],
        "ticker": ticker,
    }


# Endpoint sync a proposito: el cuerpo es I/O sqlalchemy y servicios
# sincronos (shadow LangGraph, ThesisService, NewsService) y FastAPI lo
# ejecuta en el threadpool. Como ``async def`` bloqueaba el event loop del
# proceso durante toda la ejecucion del workflow. Las dos ramas MAF (la
# unica corutina real) puentean con run_from_any_context, que en un hilo
# sin loop es un asyncio.run directo.
@router.post("/{name}/run")
def run_workflow(
    name: str,
    payload: WorkflowRunRequest,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None),
) -> dict:
    workflow = find_workflow(name)
    if not workflow:
        raise _unknown_workflow(name)
    if not workflow.get("api_executable"):
        # Honest and actionable: the entry exists but nothing consumes the
        # request. A 200 with a "not_implemented" body was a fake success.
        raise HTTPException(
            status_code=501,
            detail=(
                f"Workflow '{name}' has no execution route via the API "
                f"(execution_mode={workflow.get('execution_mode')}). {workflow.get('truth', '')}"
            ),
        )

    key = idempotency_key or payload.params.get("idempotency_key")

    def open_envelope(input_payload: dict) -> WorkflowEnvelope:
        return begin_run(
            db,
            name,
            execution_mode=workflow.get("execution_mode"),
            input_payload=input_payload,
            idempotency_key=key,
        )

    if name == "ThesisShadowComparisonWorkflow":
        from app.services.thesis_shadow_service import ThesisShadowService

        ticker = _require_ticker(payload, name)
        envelope_check = db.scalar(select(Company).where(Company.ticker == ticker))
        if not envelope_check:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
        tenant_id = db.info.get("tenant_id")
        if tenant_id is None:
            # Mismo guard que ThesisApprovalWorkflow: el thread del grafo va
            # namespacetado por tenant (thesis:{tenant}:{company}:...) y sin
            # tenant no hay namespace honesto. Antes todo corria bajo el
            # tenant fijo "shadow", identico para todos los workspaces; con
            # un checkpointer durable esos threads colisionarian entre
            # tenants (el in-memory actual no persiste, pero el namespace
            # sin tenant ya era la trampa).
            raise HTTPException(status_code=403, detail="Tenant context required")
        result = ThesisShadowService().run(
            db,
            ticker=ticker,
            tenant_external_id=str(tenant_id),
            idempotency_key=key,
        )
        if result.get("idempotent_replay"):
            # El run_id viaja en el payload grabado por el servicio. Runs
            # grabados antes de este cambio no lo llevan: se re-consulta por
            # clave de idempotencia (scoped por tenant), nunca "el ultimo".
            run_id = result.get("run_id")
            if run_id is None:
                run_id = db.scalar(
                    select(WorkflowRun.id).where(
                        WorkflowRun.workflow_name == name,
                        WorkflowRun.idempotency_key == key,
                        *tenant_filters(db, WorkflowRun),
                    )
                )
            return {
                **result,
                "run_id": run_id,
                "workflow": name,
                "steps": workflow["steps"],
                "estimated_minutes": 0,
            }
        return {
            "status": "completed",
            "workflow": name,
            "ticker": ticker,
            "run_id": result.get("run_id"),
            "result": result,
            "steps": workflow["steps"],
            "estimated_minutes": 0,
        }

    if name == "ThesisApprovalWorkflow":
        from app.services.thesis_graph_approval_service import ThesisGraphApprovalService

        ticker = _require_ticker(payload, name)
        if not db.scalar(select(Company).where(Company.ticker == ticker)):
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
        tenant_id = db.info.get("tenant_id")
        if tenant_id is None:
            raise HTTPException(status_code=403, detail="Tenant context required")
        result = ThesisGraphApprovalService().start(
            db,
            ticker=ticker,
            tenant_external_id=str(tenant_id),
            idempotency_key=key,
        )
        run_id = db.scalar(
            select(WorkflowRun.id)
            .where(
                WorkflowRun.workflow_name == name,
                *tenant_filters(db, WorkflowRun),
            )
            .order_by(WorkflowRun.id.desc())
            .limit(1)
        )
        return {
            "status": result.get("status"),
            "workflow": name,
            "ticker": ticker,
            "run_id": run_id,
            "result": result,
            "steps": workflow["steps"],
            "estimated_minutes": 0,
        }

    if name == "GenerateThesisWorkflow":
        ticker = _require_ticker(payload, name)
        company = db.scalar(select(Company).where(Company.ticker == ticker))
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
        envelope = open_envelope({"ticker": ticker, "params": payload.params})
        if envelope.replayed:
            return _replay_response(envelope, workflow, ticker)
        try:
            from app.services.thesis_service import ThesisService

            def generate() -> dict:
                thesis = ThesisService().generate(db, ticker, force_new_version=True)
                return {
                    "thesis_id": thesis.id,
                    "version": thesis.version,
                    "status": thesis.status,
                    "rating": thesis.rating,
                }

            # Un solo paso ejecutado: la generacion es una transaccion sincrona.
            result = envelope.record_step(1, "generate_thesis", generate)
            envelope.finish({"status": "completed", "result": result})
            return {
                "status": "completed",
                "workflow": name,
                "ticker": ticker,
                "run_id": envelope.run.id,
                "result": result,
                "steps": workflow["steps"],
                "estimated_minutes": 0,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=safe_detail(exc, 500)) from exc

    if name == "DailyResearchWorkflow":
        from app.schemas import NewsFeedItem
        from app.services.news_service import NewsService

        news_items = payload.params.get("news_items")
        if not news_items:
            raise HTTPException(
                status_code=422,
                detail=(
                    "DailyResearchWorkflow executes exactly one stage: news ingestion. "
                    "Send params.news_items (non-empty) or use POST /api/news/ingest. "
                    "The remaining daily stages run in the daily_research scheduled job."
                ),
            )
        # Validar ANTES de abrir el run: un payload invalido es un 422 sin
        # mas. Antes la validacion iba despues de begin_run y una
        # ValidationError salia como 500 dejando el workflow_runs colgado
        # en "running" para siempre.
        try:
            items = [NewsFeedItem.model_validate(item) for item in news_items]
        except ValidationError as exc:
            raise _params_422(exc, context="DailyResearchWorkflow params.news_items") from exc
        envelope = open_envelope({"ticker": payload.ticker, "params": payload.params})
        if envelope.replayed:
            return _replay_response(envelope, workflow, payload.ticker)

        def ingest() -> dict:
            result = NewsService().ingest_news_items(
                db,
                items,
                payload.params.get("source", "daily_research_feed"),
            )
            return result.model_dump(mode="json")

        result = envelope.record_step(1, "ingest_news_items", ingest)
        envelope.finish({"status": "completed", "result": result})
        return {
            "status": "completed",
            "workflow": name,
            "ticker": payload.ticker,
            "run_id": envelope.run.id,
            "message": "Daily research news ingestion completed.",
            "steps": workflow["steps"],
            "estimated_minutes": 0,
            "result": result,
        }

    if name == "EarningsWorkflow":
        from app.services.earnings_service import EarningsWorkflowService
        from app.workflows.maf_runtime import NativeMAFStep, NativeMAFWorkflowRunner

        ticker = _require_ticker(payload, name)
        company = db.scalar(select(Company).where(Company.ticker == ticker))
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
        # Intake validado antes de abrir el run (ver EarningsRunParams).
        try:
            earnings_params = EarningsRunParams.model_validate(payload.params)
        except ValidationError as exc:
            raise _params_422(exc, context="EarningsWorkflow params") from exc

        def load_context(state: dict) -> dict:
            return {
                "ticker": ticker,
                "fiscal_year": earnings_params.fiscal_year,
                "fiscal_quarter": earnings_params.fiscal_quarter,
                "document_ids": earnings_params.document_ids,
            }

        def execute_review(state: dict) -> dict:
            run = EarningsWorkflowService().run(
                db,
                company,
                fiscal_year=state["fiscal_year"],
                fiscal_quarter=state["fiscal_quarter"],
                document_ids=state["document_ids"],
                force_new_thesis=earnings_params.force_new_thesis,
            )
            return {
                "run": {
                    "status": run.status,
                    "error": run.error,
                    "earnings_run_id": run.id,
                    "thesis_change_id": run.thesis_change_id,
                    "documents": run.document_ids,
                    "metrics": len(run.extracted_metrics),
                    "guidance_changes": len(run.guidance_changes),
                }
            }

        # El envelope graba los params ya normalizados: lo que corre es lo
        # que queda firmado en input_payload.
        envelope = open_envelope({"ticker": ticker, "params": earnings_params.model_dump()})
        if envelope.replayed:
            return _replay_response(envelope, workflow, ticker)
        maf_result = run_from_any_context(
            NativeMAFWorkflowRunner(
                name,
                [
                    NativeMAFStep("load_earnings_context", load_context),
                    NativeMAFStep("execute_earnings_review", execute_review),
                ],
                recorder=envelope.record_step,
            ).run({"ticker": ticker})
        )
        run = maf_result["run"]
        result = {
            "earnings_run_id": run["earnings_run_id"],
            "thesis_change_id": run["thesis_change_id"],
            "documents": run["documents"],
            "metrics": run["metrics"],
            "guidance_changes": run["guidance_changes"],
        }
        if run["status"] == "completed":
            envelope.finish({"status": "completed", "result": result})
        else:
            envelope.run.status = "failed"
            envelope.run.error_message = (run["error"] or "Earnings workflow failed")[:1000]
            from app.services.workflow_run_service import _safe_commit

            _safe_commit(db, "earnings run failed")
        return {
            "status": run["status"],
            "workflow": name,
            "execution_mode": maf_result["execution_mode"],
            "ticker": ticker,
            "run_id": envelope.run.id,
            "message": run["error"] or "Earnings workflow completed.",
            "steps": workflow["steps"],
            "estimated_minutes": 0,
            "result": result,
        }

    if name == "RedTeamWorkflow":
        from app.services.red_team_service import RedTeamService
        from app.workflows.maf_runtime import NativeMAFStep, NativeMAFWorkflowRunner

        ticker = _require_ticker(payload, name)
        company = db.scalar(select(Company).where(Company.ticker == ticker))
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")

        def load_evidence(state: dict) -> dict:
            return {"ticker": ticker, "review_scope": "thesis_evidence_and_assumptions"}

        def execute_red_team(state: dict) -> dict:
            run = RedTeamService().run(db, company)
            return {
                "run": {
                    "status": run.status,
                    "red_team_run_id": run.id,
                    "score": run.score,
                    "findings": len(run.findings),
                }
            }

        envelope = open_envelope({"ticker": ticker, "params": payload.params})
        if envelope.replayed:
            return _replay_response(envelope, workflow, ticker)
        maf_result = run_from_any_context(
            NativeMAFWorkflowRunner(
                name,
                [
                    NativeMAFStep("load_review_evidence", load_evidence),
                    NativeMAFStep("execute_adversarial_review", execute_red_team),
                ],
                recorder=envelope.record_step,
            ).run({"ticker": ticker})
        )
        run = maf_result["run"]
        result = {
            "red_team_run_id": run["red_team_run_id"],
            "score": run["score"],
            "findings": run["findings"],
        }
        envelope.finish({"status": "completed", "result": result})
        return {
            "status": run["status"],
            "workflow": name,
            "execution_mode": maf_result["execution_mode"],
            "ticker": ticker,
            "run_id": envelope.run.id,
            "message": "Red-team workflow completed.",
            "steps": workflow["steps"],
            "estimated_minutes": 0,
            "result": result,
        }

    # Every catalog entry has a branch above. If one is ever added without it,
    # say so instead of returning a 200 that ran nothing.
    raise HTTPException(
        status_code=501,
        detail=(
            f"Workflow '{name}' is in the catalog but has no execution branch in this route. "
            "Nothing was executed and no run was recorded."
        ),
    )


class WorkflowDecisionRequest(BaseModel):
    thread_id: str
    decision: str
    notes: str | None = None


@router.post("/{name}/decide")
def decide_workflow(
    name: str,
    payload: WorkflowDecisionRequest,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None),
) -> dict:
    """Resume a paused workflow with a human decision (6c approval gate)."""
    if name != "ThesisApprovalWorkflow":
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' does not accept decisions")
    from app.services.thesis_graph_approval_service import DECISIONS, ThesisGraphApprovalService

    if payload.decision not in DECISIONS:
        raise HTTPException(
            status_code=422,
            detail=f"decision must be one of {sorted(DECISIONS)}",
        )
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="Tenant context required")
    result = ThesisGraphApprovalService().decide(
        db,
        thread_id=payload.thread_id,
        tenant_external_id=str(tenant_id),
        decision=payload.decision,
        notes=payload.notes,
        actor="api",
        idempotency_key=idempotency_key,
    )
    return {"workflow": name, **result}
